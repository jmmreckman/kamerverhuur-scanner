"""Bewaart het resultaat van de laatste 'check betalingen'-run per pand in een
klein JSON-bestandje, zodat de website dat kan tonen zonder bij elk
paginabezoek opnieuw bunq/Sheets te hoeven bevragen."""
from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .models import Payment, TenantResult
from .utils import nu_amsterdam


def _bestandsnaam(pand_slug: str, state_dir: str = ".") -> Path:
    veilige_slug = re.sub(r"[^a-z0-9_-]", "-", pand_slug.lower())
    return Path(state_dir) / f"laatste_resultaat_{veilige_slug}.json"


def save(
    pand_slug: str,
    results: list[TenantResult],
    niet_gekoppelde_betalingen: int,
    state_dir: str = ".",
    unmatched_payments: list[Payment] | None = None,
) -> None:
    """`unmatched_payments` is optioneel (de details van de niet-gekoppelde
    betalingen zelf, i.p.v. alleen het aantal) - zonder dit blijft de
    dashboard-melding werken (die gebruikt alleen het aantal), maar toont de
    betalingenpagina bij het volgende bezoek (buiten een verse "Nu
    controleren"-klik om) geen tabel met wie die betalingen deed. Bewaard als
    kant-en-klare weergavetekst (net als de rest van dit bestand), niet als
    losse datum-/bedragvelden - dit is puur voor tonen, niet voor verder
    rekenen."""
    data = {
        "gecontroleerd_op": nu_amsterdam().strftime("%d-%m-%Y %H:%M"),
        "resultaten": [
            {
                "kamer": r.tenant.kamer,
                "naam": r.tenant.naam,
                "verwacht_bedrag": str(r.tenant.verwacht_bedrag),
                "ontvangen_bedrag": str(r.ontvangen_bedrag),
                "status": r.status.value,
            }
            for r in results
        ],
        "niet_gekoppelde_betalingen": niet_gekoppelde_betalingen,
        "niet_gekoppelde_betalingen_lijst": [
            {
                "datum": p.datum.strftime("%d-%m-%Y"),
                "tegenpartij_naam": p.tegenpartij_naam,
                "bedrag": str(p.bedrag),
                "omschrijving": p.omschrijving,
            }
            for p in (unmatched_payments or [])
        ],
    }
    _bestandsnaam(pand_slug, state_dir).write_text(json.dumps(data, indent=2))


def load(pand_slug: str, state_dir: str = ".") -> dict | None:
    p = _bestandsnaam(pand_slug, state_dir)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def status_voor_kamer(cache: dict | None, kamer: str) -> dict | None:
    if not cache:
        return None
    for regel in cache["resultaten"]:
        if regel["kamer"] == kamer:
            return regel
    return None


def _verzonden_bestandsnaam(pand_slug: str, state_dir: str = ".") -> Path:
    veilige_slug = re.sub(r"[^a-z0-9_-]", "-", pand_slug.lower())
    return Path(state_dir) / f"verzonden_mails_{veilige_slug}.json"


def markeer_email_verzonden(pand_slug: str, kamer: str, soort: str, maand: str, state_dir: str = ".") -> None:
    """Onthoudt dat een herinnering/ingebrekestelling daadwerkelijk verstuurd
    is voor deze kamer, deze maand - alleen aanroepen ná een geslaagde
    verstuur_email(), niet meteen bij het klikken op de knop. Reset vanzelf
    zodra er een nieuwe maand is (andere `maand`-sleutel)."""
    p = _verzonden_bestandsnaam(pand_slug, state_dir)
    data = json.loads(p.read_text()) if p.exists() else {}
    data[f"{kamer}|{soort}|{maand}"] = nu_amsterdam().strftime("%d-%m-%Y %H:%M")
    p.write_text(json.dumps(data, indent=2))


def email_verzonden_op(pand_slug: str, kamer: str, soort: str, maand: str, state_dir: str = ".") -> str | None:
    p = _verzonden_bestandsnaam(pand_slug, state_dir)
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    return data.get(f"{kamer}|{soort}|{maand}")


def _aanzeggingen_bestandsnaam(pand_slug: str, state_dir: str = ".") -> Path:
    veilige_slug = re.sub(r"[^a-z0-9_-]", "-", pand_slug.lower())
    return Path(state_dir) / f"afgehandelde_aanzeggingen_{veilige_slug}.json"


def markeer_aanzegging_afgehandeld(pand_slug: str, kamer: str, einddatum: str, state_dir: str = ".") -> None:
    """Onthoudt dat de aanzeg-waarschuwing voor deze kamer/einddatum is
    weggeklikt (de aanzegging is al gedaan). Gesleuteld op (kamer, einddatum)
    zodat een nieuw contract met een andere einddatum vanzelf weer een
    (nieuwe) waarschuwing geeft."""
    p = _aanzeggingen_bestandsnaam(pand_slug, state_dir)
    data = json.loads(p.read_text()) if p.exists() else {}
    data[f"{kamer}|{einddatum}"] = nu_amsterdam().strftime("%d-%m-%Y %H:%M")
    p.write_text(json.dumps(data, indent=2))


def aanzegging_is_afgehandeld(pand_slug: str, kamer: str, einddatum: str, state_dir: str = ".") -> bool:
    p = _aanzeggingen_bestandsnaam(pand_slug, state_dir)
    if not p.exists():
        return False
    data = json.loads(p.read_text())
    return f"{kamer}|{einddatum}" in data


def _winst_geschiedenis_bestandsnaam(pand_slug: str, state_dir: str = ".") -> Path:
    veilige_slug = re.sub(r"[^a-z0-9_-]", "-", pand_slug.lower())
    return Path(state_dir) / f"winst_geschiedenis_{veilige_slug}.json"


def voeg_winst_snapshot_toe(pand_slug: str, winst: Decimal, state_dir: str = ".") -> None:
    """Voegt een winst-datapunt toe voor vandaag (overschrijft een eventueel
    al bestaand punt van dezelfde dag, zodat vaker draaien op 1 dag geen
    dubbele punten in de grafiek geeft) - wekelijks aangeroepen door
    scripts/winst_snapshot.py, zodat de grafiek op de winstpagina langzaam
    langer wordt. Bewaart alleen datum + winst (geen inkomsten/lasten-detail
    - dat verandert toch elke keer je 'm bekijkt, de grafiek is puur voor de
    trend over tijd)."""
    p = _winst_geschiedenis_bestandsnaam(pand_slug, state_dir)
    data = json.loads(p.read_text()) if p.exists() else []
    vandaag = nu_amsterdam().strftime("%Y-%m-%d")
    data = [punt for punt in data if punt["datum"] != vandaag]
    data.append({"datum": vandaag, "winst": str(winst)})
    data.sort(key=lambda punt: punt["datum"])
    p.write_text(json.dumps(data, indent=2))


def laad_winst_geschiedenis(pand_slug: str, state_dir: str = ".") -> list[dict]:
    p = _winst_geschiedenis_bestandsnaam(pand_slug, state_dir)
    if not p.exists():
        return []
    return json.loads(p.read_text())


def _testaccount_logboek_bestandsnaam(state_dir: str = ".") -> Path:
    return Path(state_dir) / "testaccount_logboek.json"


# Hoeveel login-regels we maximaal bewaren (nieuwste onderaan) - genoeg om een
# tijd terug te kijken, maar voorkomt dat het bestand oneindig groeit.
_TESTACCOUNT_LOGBOEK_MAX = 1000


def log_testaccount_login(gebruiker: str, ip: str | None, state_dir: str = ".") -> None:
    """Legt vast dat een testaccount is ingelogd (tijdstip + gebruikersnaam +
    IP-adres), zodat de hoofdgebruiker kan zien óf en hoe vaak een tester
    daadwerkelijk inlogt (zie webapp/app.py: test_account_logboek())."""
    p = _testaccount_logboek_bestandsnaam(state_dir)
    data = json.loads(p.read_text()) if p.exists() else []
    data.append({
        "tijd": nu_amsterdam().strftime("%d-%m-%Y %H:%M"),
        "gebruiker": gebruiker,
        "ip": ip or "",
    })
    p.write_text(json.dumps(data[-_TESTACCOUNT_LOGBOEK_MAX:], indent=2))


def laad_testaccount_logboek(state_dir: str = ".") -> list[dict]:
    """Alle login-regels van testaccounts (oudste eerst, zoals opgeslagen)."""
    p = _testaccount_logboek_bestandsnaam(state_dir)
    if not p.exists():
        return []
    return json.loads(p.read_text())


def _komende_maand_bestandsnaam(pand_slug: str, state_dir: str = ".") -> Path:
    veilige_slug = re.sub(r"[^a-z0-9_-]", "-", pand_slug.lower())
    return Path(state_dir) / f"komende_maand_{veilige_slug}.json"


def bewaar_komende_maand(pand_slug: str, maand: str, resultaten: list[dict], state_dir: str = ".") -> None:
    """Bewaart de (langzame, live opgehaalde) vooruitbetaal-controle voor de
    komende maand per pand, zodat de "Totaal overzicht"-pagina die meteen uit
    cache kan tonen i.p.v. bij elk bezoek opnieuw bunq/Sheets te bevragen.
    `maand` is de doelmaand als "YYYY-MM", zodat een cache van vorige maand
    vanzelf verouderd (en dus genegeerd) raakt. `resultaten` is een lijst dicts
    met verwacht_bedrag/ontvangen_bedrag/status (kant-en-klaar om op te tellen)."""
    data = {
        "berekend_op": nu_amsterdam().strftime("%d-%m-%Y %H:%M"),
        "maand": maand,
        "resultaten": resultaten,
    }
    _komende_maand_bestandsnaam(pand_slug, state_dir).write_text(json.dumps(data, indent=2))


def laad_komende_maand(pand_slug: str, state_dir: str = ".") -> dict | None:
    p = _komende_maand_bestandsnaam(pand_slug, state_dir)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _genegeerde_lasten_bestandsnaam(pand_slug: str, state_dir: str = ".") -> Path:
    veilige_slug = re.sub(r"[^a-z0-9_-]", "-", pand_slug.lower())
    return Path(state_dir) / f"genegeerde_lasten_{veilige_slug}.json"


def negeer_last(pand_slug: str, sleutel: str, omschrijving: str, state_dir: str = ".") -> None:
    """Zet een tegenpartij (zie kamerverhuur_scanner.winst._tegenpartij_sleutel)
    definitief op de negeerlijst van dit pand - komt daarna nooit meer voor
    als "vaste last" op de winstpagina, ongeacht hoe vaak/regelmatig 'ie
    terugkomt (zie webapp/app.py: winst_last_negeren())."""
    p = _genegeerde_lasten_bestandsnaam(pand_slug, state_dir)
    data = json.loads(p.read_text()) if p.exists() else {}
    data[sleutel] = omschrijving
    p.write_text(json.dumps(data, indent=2))


def verwijder_genegeerde_last(pand_slug: str, sleutel: str, state_dir: str = ".") -> None:
    """Haalt een tegenpartij weer van de negeerlijst af (zie webapp/app.py:
    winst_negeerlijst_herstellen()) - komt daarna weer gewoon in aanmerking
    als vaste last zodra 'ie weer aan de herkenningsregels voldoet."""
    p = _genegeerde_lasten_bestandsnaam(pand_slug, state_dir)
    if not p.exists():
        return
    data = json.loads(p.read_text())
    data.pop(sleutel, None)
    p.write_text(json.dumps(data, indent=2))


def laad_genegeerde_lasten(pand_slug: str, state_dir: str = ".") -> dict[str, str]:
    """Geeft {sleutel: omschrijving} van alle genegeerde tegenpartijen van
    dit pand."""
    p = _genegeerde_lasten_bestandsnaam(pand_slug, state_dir)
    if not p.exists():
        return {}
    return json.loads(p.read_text())
