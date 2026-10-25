"""Parser voor een geexporteerde WhatsApp-chat (het .txt-bestand uit
'Chat exporteren -> zonder media'). Puur en zonder externe dependencies, zodat
het in de sandbox te testen is. De route in app.py roept parse_whatsapp_export()
aan en zet de berichten daarna via communicatie_db.voeg_bericht_toe() in de
tijdlijn (met een gesynthetiseerd message_id, zodat opnieuw importeren niet
dubbel toevoegt).

WhatsApp-exportregels verschillen per toestel/landinstelling. We ondersteunen de
gangbare vormen, bijvoorbeeld:
    [25-10-2026, 14:12:33] Nushka: Hoi, de kraan lekt weer
    25/10/2026, 14:12 - Jurian: Ik stuur de loodgieter
    2026-10-25, 14:12 - Nushka: ok
Een bericht kan over meerdere regels lopen (vervolgregels hebben geen tijdstempel
en horen bij het vorige bericht). Systeemregels (versleuteling, '<media
weggelaten>') worden overgeslagen.
"""
from __future__ import annotations

import hashlib
import re

# Begin van een bericht: optioneel '[', datum, tijd, afsluiting ']' of ' - ',
# daarna 'Afzender: tekst'. Datum en tijd worden los opgevangen en daarna
# soepel geparset (dag-eerst voor NL, of ISO als het jaar vooraan staat).
_REGELKOP = re.compile(
    r"^\[?\s*"
    r"(?P<datum>\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4})"
    r"[,]?\s+"
    r"(?P<tijd>\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap][.]?[Mm][.]?)?)"
    r"\s*\]?\s*[-–]?\s+"
    r"(?P<rest>.*)$"
)

# Regels die WhatsApp zelf toevoegt en die geen echt bericht zijn.
_SYSTEEM_FRAGMENTEN = (
    "end-to-end",
    "versleuteld",
    "encrypted",
    "<media weggelaten>",
    "<media omitted>",
    "media weggelaten",
    "media omitted",
    "berichten en gesprekken zijn",
    "je hebt dit groepsgesprek",
    "heeft dit groepsgesprek",
    "beveiligd met end-to-end",
)


def _parse_datum(datum: str, tijd: str) -> str | None:
    """Combineert een WhatsApp-datum en -tijd tot een ISO-8601 string. Geeft None
    als het niet te parsen valt. Gaat uit van dag-eerst (NL/EU), tenzij het jaar
    duidelijk vooraan staat (ISO). Tijd mag 12-uurs met am/pm zijn."""
    delen = re.split(r"[-/.]", datum)
    if len(delen) != 3:
        return None
    try:
        getallen = [int(d) for d in delen]
    except ValueError:
        return None

    if len(delen[0]) == 4:  # ISO: jaar-maand-dag
        jaar, maand, dag = getallen
    else:  # dag-eerst (NL/EU): dag-maand-jaar
        dag, maand, jaar = getallen
        if jaar < 100:
            jaar += 2000

    uur, minuut, seconde, ampm = _parse_tijd(tijd)
    if uur is None:
        return None
    if ampm == "pm" and uur < 12:
        uur += 12
    elif ampm == "am" and uur == 12:
        uur = 0

    if not (1 <= maand <= 12 and 1 <= dag <= 31 and 0 <= uur <= 23 and 0 <= minuut <= 59):
        return None
    return f"{jaar:04d}-{maand:02d}-{dag:02d}T{uur:02d}:{minuut:02d}:{seconde:02d}+00:00"


def _parse_tijd(tijd: str):
    m = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s?([APap][.]?[Mm][.]?)?", tijd.strip())
    if not m:
        return None, None, None, None
    uur, minuut = int(m.group(1)), int(m.group(2))
    seconde = int(m.group(3)) if m.group(3) else 0
    ampm = None
    if m.group(4):
        ampm = "am" if m.group(4).lower().startswith("a") else "pm"
    return uur, minuut, seconde, ampm


def _is_systeemregel(rest: str) -> bool:
    laag = rest.lower()
    return any(fragment in laag for fragment in _SYSTEEM_FRAGMENTEN)


def _normaliseer_naam(naam: str) -> str:
    return (naam or "").strip().lower()


def parse_whatsapp_export(tekst: str, *, eigen_namen) -> list[dict]:
    """Parset een geexporteerde WhatsApp-chat tot een lijst berichten
    (chronologisch zoals in de export). Elk bericht is een dict met:
        datum (ISO of None), afzender, richting ('in'/'uit'), body.
    `eigen_namen` is een verzameling namen (zoals ze in de chat staan) die als de
    beheerder gelden -> die berichten krijgen richting 'uit', de rest 'in'.
    Systeemregels en lege berichten worden overgeslagen."""
    eigen = {_normaliseer_naam(n) for n in eigen_namen if _normaliseer_naam(n)}
    berichten: list[dict] = []
    for ruwe_regel in (tekst or "").splitlines():
        # WhatsApp zet soms een onzichtbaar LRM/opmaakteken aan het begin.
        regel = ruwe_regel.replace("‎", "").replace("‏", "").rstrip("\r")
        kop = _REGELKOP.match(regel)
        if not kop:
            # Vervolgregel: bij het vorige bericht plakken (meerregelig bericht).
            if berichten and regel.strip():
                berichten[-1]["body"] += "\n" + regel
            continue
        rest = kop.group("rest")
        if ":" not in rest or _is_systeemregel(rest):
            # Systeemmelding ('... zijn versleuteld') of statusregel zonder afzender.
            continue
        afzender, _, body = rest.partition(":")
        afzender, body = afzender.strip(), body.strip()
        if not afzender:
            continue
        richting = "uit" if _normaliseer_naam(afzender) in eigen else "in"
        berichten.append({
            "datum": _parse_datum(kop.group("datum"), kop.group("tijd")),
            "afzender": afzender,
            "richting": richting,
            "body": body,
        })
    # Lege body's (bv. enkel '<media weggelaten>' dat al eruit viel) weglaten.
    return [b for b in berichten if b["body"].strip()]


def synthetiseer_message_id(contact_id: int, datum: str | None, afzender: str, body: str) -> str:
    """Stabiel message_id voor een WhatsApp-bericht (dat zelf geen Message-ID
    heeft), zodat opnieuw importeren van dezelfde export niet dubbel toevoegt.
    Gebaseerd op contact + datum + afzender + inhoud."""
    sleutel = f"{contact_id}|{datum or ''}|{_normaliseer_naam(afzender)}|{body.strip()}"
    digest = hashlib.sha1(sleutel.encode("utf-8")).hexdigest()[:20]
    return f"wa:{contact_id}:{digest}"
