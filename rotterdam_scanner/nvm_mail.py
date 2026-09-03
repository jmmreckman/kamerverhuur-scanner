"""Tweede bron voor kansen.steenhub.nl: de NVM-/makelaarsmails in Move.nl-opmaak.

Een NVM-makelaar zet in Realworks/Move.nl een zoekprofiel aan dat álle matchende
koopwoningen naar de scanner-mailbox stuurt - zónder de Funda-consumentencap. Deze
module leest die mails en levert dezelfde `FundaListing`-objecten als de Funda-scan
(met `bron="nvm"`), zodat ze via exact dezelfde pipeline lopen en op object_id
(POSTCODE-HUISNUMMER[TOEVOEGING]) automatisch ontdubbelen met de Funda-bron. De
Funda-scan blijft ernaast draaien en vult ontbrekende velden (zoals de Funda-link)
aan.

Formaat per woning in de mail (platte-tekstdeel, één blok):

    Match: 100%
    Westzeedijk 74 B3016 AG Rotterdam
    Vraagprijs: € 485.000,- kosten koper
    Bovenwoning | 63 m² | 3 kamers (2 slaapkamers)

De postcode (4 cijfers + 2 letters) plakt in de platte tekst direct achter het
huisnummer/toevoeging; daar splitsen we op. De prijsregel heet "Vraagprijs" of
"Koopsom"; een enkele woning heeft geen prijs (dan None).
"""
from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime, timedelta
from email.message import Message

from .config import Config
from .funda_mail import FundaListing, _maak_object_id

# Standaardonderwerp van een Move.nl-zoekopdrachtmail - robuuster dan op afzender
# filteren (werkt voor elke NVM-makelaar die zo'n profiel voor je aanzet).
_STANDAARD_ONDERWERP = "gevonden voor uw zoekopdracht"

# Adresregel: alles vóór de postcode is straat + huisnummer(+toevoeging); de postcode
# (4 cijfers + 2 letters) plakt er in de platte tekst direct tegenaan. Een eventuele
# complexnaam staat tussen haakjes achter de plaats.
_ADRES_RE = re.compile(
    r"^(?P<voor>.*?)(?P<pc4>\d{4})\s+(?P<pcl>[A-Z]{2})\s+(?P<plaats>[^(]+?)(?:\s*\(.*\))?\s*$"
)
# Straat + huisnummer + toevoeging: het huisnummer is het láátste losse getal (een
# straat kan zelf ook een cijfer bevatten, bv. "2e Antonie Heinsiusstraat").
_STRAATNR_RE = re.compile(r"^(?P<straat>.*?)\s+(?P<huisnr>\d+)\s*(?P<toev>[A-Za-z0-9]*)$")
_PRIJS_RE = re.compile(r"(?:Vraagprijs|Koopsom)\s*:\s*€\s*(?P<prijs>[\d.]+)", re.IGNORECASE)
_M2_RE = re.compile(r"(?P<m2>\d+)\s*m²")


def _beste_tekst(msg: Message) -> str:
    """Prefereert het text/plain-deel (Move.nl levert een schoon platte-tekstdeel met
    één woning per blok); valt terug op ruwe HTML als er geen tekstdeel is."""
    text_part = None
    html_part = None
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/plain" and text_part is None:
            text_part = part
        elif ct == "text/html" and html_part is None:
            html_part = part
    chosen = text_part or html_part
    if chosen is None:
        return ""
    payload = chosen.get_payload(decode=True) or b""
    charset = chosen.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _parse_adres(adresregel: str):
    """(straat, huisnummer, toevoeging, postcode, plaats) of None."""
    regel = re.sub(r"\s+", " ", adresregel).strip()
    a = _ADRES_RE.match(regel)
    if not a:
        return None
    sn = _STRAATNR_RE.match(a.group("voor").strip())
    if not sn:
        return None
    postcode = f"{a.group('pc4')} {a.group('pcl')}"
    return (
        sn.group("straat").strip(),
        sn.group("huisnr"),
        sn.group("toev").strip().upper(),
        postcode,
        a.group("plaats").strip(),
    )


def parse_nvm_body(tekst: str) -> tuple[list[FundaListing], list[str]]:
    """Haalt de woningen uit het platte-tekstdeel van een NVM-/Move.nl-mail.

    Geeft (woningen, onherkende_adresregels) terug. Elke woning is een FundaListing
    met bron='nvm'; het object_id (POSTCODE-HUISNUMMER[TOEVOEGING]) is identiek aan
    dat van de Funda-scan, zodat dezelfde woning uit beide bronnen ontdubbelt."""
    woningen: dict[str, FundaListing] = {}
    onherkend: list[str] = []

    # Elk woningblok begint met "Match: X%"; het eerste stuk (de aanhef) valt af.
    for blok in re.split(r"Match:\s*\d+%", tekst)[1:]:
        regels = [r.strip() for r in blok.strip().splitlines() if r.strip()]
        if not regels:
            continue
        parsed = _parse_adres(regels[0])
        if not parsed:
            onherkend.append(regels[0])
            continue
        straat, huisnr, toev, postcode, plaats = parsed

        prijs = None
        for regel in regels[1:]:
            m = _PRIJS_RE.search(regel)
            if m:
                prijs = int(m.group("prijs").replace(".", ""))
                break

        oppervlakte = None
        typeregel = next((r for r in regels[1:] if "m²" in r or "kamer" in r.lower()), "")
        m2 = _M2_RE.search(typeregel)  # bij "157 m² / 70 m²" pakt dit de eerste (woonopp.)
        if m2:
            oppervlakte = int(m2.group("m2"))

        object_id = _maak_object_id(postcode, huisnr, toev)
        if not object_id:
            onherkend.append(regels[0])
            continue
        # Binnen één mail kan dezelfde woning niet dubbel; laat de eerste staan.
        woningen.setdefault(object_id, FundaListing(
            object_id=object_id,
            url="",  # NVM-mail heeft geen Funda-link; de Funda-bron vult die later aan
            straatnaam=straat,
            huisnummer=huisnr,
            toevoeging=toev,
            postcode=postcode.replace(" ", ""),
            woonplaats=plaats,
            prijs=prijs,
            oppervlakte_advertentie=oppervlakte,
            bron="nvm",
        ))

    return list(woningen.values()), onherkend


def haal_nvm_woningen(config: Config, lookback_days: int = 3) -> tuple[list[FundaListing], list[str]]:
    """Leest de recente NVM-/Move.nl-mails uit de scanner-mailbox en parseert ze.

    Er komen er veel per dag (elke zoekopdracht/melding is een aparte mail), dus we
    lezen álle mails met het Move.nl-standaardonderwerp binnen het venster en
    ontdubbelen over de mails heen op object_id. Geeft (woningen, waarschuwingen)."""
    woningen: dict[str, FundaListing] = {}
    waarschuwingen: list[str] = []

    with imaplib.IMAP4_SSL(config.imap_host) as imap:
        imap.login(config.gmail_address, config.gmail_app_password)
        imap.select(config.funda_mail_folder)
        since = (datetime.now() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f'(SINCE "{since}" SUBJECT "{_STANDAARD_ONDERWERP}")')
        if status != "OK":
            raise RuntimeError(f"IMAP-zoekopdracht (NVM) mislukt: {status}")

        for msg_id in data[0].split():
            ok, msg_data = imap.fetch(msg_id, "(RFC822)")
            if ok != "OK" or not msg_data or msg_data[0] is None:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            tekst = _beste_tekst(msg)
            gevonden, onherkend = parse_nvm_body(tekst)
            for listing in gevonden:
                woningen.setdefault(listing.object_id, listing)
            waarschuwingen.extend(
                f"NVM-mail: adres niet herkend: {regel!r}" for regel in onherkend
            )

    return list(woningen.values()), waarschuwingen
