"""Welke soorten mail een beheerder via BCC (of als rechtstreekse ontvanger
van een melding) binnenkrijgt, en of ze zich daar per type voor hebben
afgemeld - zie de "Mailvoorkeuren"-pagina in de webapp
(webapp/app.py: mail_voorkeuren_overzicht()).

Blijft aanvullend op EMAIL_BCC/EMAIL_BCC_BEHEERDER (.env) en extra_bcc
(properties.json): die blijven gewoon bestaan voor adressen zonder account
op de site (bv. een mede-eigenaar die de site zelf niet gebruikt). Wie wél
een account + e-mailadres heeft ingevuld, kan zich per type afmelden - zo'n
adres wordt dan uit de bestaande adressenlijst gefilterd, ook als het daar
al in stond via EMAIL_BCC."""
from __future__ import annotations

import json
from pathlib import Path

# key -> (korte titel, uitleg) - getoond op de Mailvoorkeuren-pagina.
NOTIFICATIE_TYPES: dict[str, tuple[str, str]] = {
    "huishouden": (
        "Mail het hele huishouden",
        "Groepsmails naar (huidige of recent vertrokken) huurders van een pand, incl. \"Licht huurders in\".",
    ),
    "communicatie": (
        "Communicatie per huurder",
        "Mails die je verstuurt via het AI-sparpaneel op de Communicatie-pagina van een huurder.",
    ),
    "herinneringen": (
        "Betaalherinneringen & ingebrekestellingen",
        "Als er een herinnering of ingebrekestelling naar een huurder wordt gestuurd vanaf de Betalingen-pagina.",
    ),
    "contracten": (
        "Huurcontracten",
        "Concept-contract mailen, ondertekenverzoeken (+ herinneringen daaraan), en de bevestigingsmail zodra "
        "een contract getekend en betaald is.",
    ),
    "bezichtigingen": (
        "Bezichtigingen",
        "Het overzicht van ingeplande bezichtigingen, en de bevestigings-/afwijzingsmails naar aanmelders.",
    ),
    "aanmeldingen": (
        "Nieuwe aanmeldingen",
        "Melding zodra iemand via de publieke aanbodpagina op een kamer reageert.",
    ),
    "betalingsstatus": (
        "\"Alles betaald\"-melding",
        "Automatisch bericht zodra de huur van alle kamers van een pand in een maand volledig binnen is.",
    ),
}


def laad_users(users_file: str) -> dict:
    """Zelfde als webapp.auth.load_users(), maar zonder een afhankelijkheid
    van de webapp-laag - dit pakket (kamerverhuur_scanner) moet ook zonder
    Flask bruikbaar blijven (zie scripts/dagelijkse_controle.py)."""
    pad = Path(users_file)
    if not pad.exists():
        return {}
    try:
        return json.loads(pad.read_text())
    except json.JSONDecodeError:
        return {}


def wil_ontvangen(gebruiker: dict, type_key: str) -> bool:
    """Standaard AAN (opt-out, geen opt-in) - zo verandert er niets voor
    bestaande gebruikers totdat ze zelf iets uitvinken op de
    Mailvoorkeuren-pagina."""
    return gebruiker.get("mail_voorkeuren", {}).get(type_key, True)


def heeft_toegang(gebruiker: dict, pand_slug: str) -> bool:
    return bool(gebruiker.get("alle_panden")) or pand_slug in gebruiker.get("panden", [])


def ontvangers(users: dict, pand_slug: str, type_key: str, basis: list[str]) -> list[str]:
    """Past de mailvoorkeuren toe op `basis` (de bestaande adressenlijst uit
    EMAIL_BCC/EMAIL_BCC_BEHEERDER/extra_bcc): adressen daarvan die bij een
    account met dit type uitgevinkt horen worden eruit gefilterd, en
    gebruikers met toegang tot dit pand die dit type nog willen (en nog
    niet in `basis` stonden, bv. een net toegevoegd e-mailadres) worden
    toegevoegd. Adressen zonder bijbehorend account blijven onaangeroerd."""
    afgemeld = {
        gebruiker["email"].strip().lower()
        for gebruiker in users.values()
        if gebruiker.get("email") and not wil_ontvangen(gebruiker, type_key)
    }
    gefilterd = [adres for adres in basis if adres.strip().lower() not in afgemeld]
    aanvullend = [
        gebruiker["email"].strip() for gebruiker in users.values()
        if gebruiker.get("email") and heeft_toegang(gebruiker, pand_slug) and wil_ontvangen(gebruiker, type_key)
    ]
    # Case-insensitief dedupliceren: als iemands EMAIL_BCC-adres en het adres
    # dat ze zelf op de Mailvoorkeuren-pagina invullen alleen in hoofdletter-
    # gebruik verschillen, mag dat niet leiden tot een dubbele mail.
    gezien: set[str] = set()
    resultaat = []
    for adres in gefilterd + aanvullend:
        sleutel = adres.strip().lower()
        if sleutel not in gezien:
            gezien.add(sleutel)
            resultaat.append(adres)
    return resultaat
