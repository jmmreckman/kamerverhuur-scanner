"""Automatisch wegschrijven van getekende contracten (en later: aangeleverde
documenten) naar de eigen Google Drive van de gebruiker, via rclone.

Waarom niet het bestaande service account (drive_client.py)? Dat heeft zelf
0 GB Drive-opslag - uploaden daarmee naar een gewone, persoonlijke Drive-map
mislukt altijd met "storageQuotaExceeded" (zie lokale_media.py). rclone
gebruikt in plaats daarvan een echte, eenmalige inlog met het eigen
Google-account van de gebruiker (via rclone's eigen, al door Google
goedgekeurde OAuth-app - dus geen maandenlange app-verificatie nodig), zodat
uploads gewoon onder de eigen (2TB+) opslag van dat account vallen. Zie
README voor de eenmalige 'rclone config'-stap.

Mappenstructuur per pand (onder RCLONE_REMOTE, bv. "gdrive:vastgoed"):
    Steenhub <pandnaam>/
        Huidige huurders/<huurdernaam>/...
        Oude huurders/<huurdernaam>/...

Alles hier is best-effort: als RCLONE_REMOTE niet is ingesteld, rclone niet
geinstalleerd is, of een upload/verplaatsing om wat voor reden dan ook
mislukt, wordt dat alleen gelogd - een haperende Drive-kopie mag nooit een
contractondertekening of huurderswijziging laten mislukken. Bestanden blijven
sowieso ook gewoon lokaal op de VPS staan."""
from __future__ import annotations

import logging
import subprocess

from .config import Config
from .models import Pand

logger = logging.getLogger(__name__)

HUIDIGE_HUURDERS = "Huidige huurders"
OUDE_HUURDERS = "Oude huurders"

_TIMEOUT_SECONDEN = 120


def pand_root(config: Config, pand: Pand) -> str | None:
    """Het rclone-pad van de hoofdmap van dit pand ("Steenhub <pandnaam>") -
    ook gebruikt door drive_browse.py om dezelfde map te doorbladeren op de
    Documenten-pagina, zodat er geen aparte, los gedeelde Drive-map meer
    nodig is naast deze automatisch aangemaakte."""
    if not config.rclone_remote:
        return None
    return f"{config.rclone_remote.rstrip('/')}/Steenhub {pand.naam}"


def _huurder_pad(config: Config, pand: Pand, huurder_naam: str, map_naam: str) -> str | None:
    root = pand_root(config, pand)
    if root is None or not huurder_naam:
        return None
    return f"{root}/{map_naam}/{huurder_naam}"


def maak_huurder_map(config: Config, pand: Pand, huurder_naam: str) -> bool:
    """Maakt (indien nog niet aanwezig) de map van een huurder onder
    'Huidige huurders' - zodat die meteen zichtbaar is in Drive, ook voordat
    er al een bestand in staat."""
    pad = _huurder_pad(config, pand, huurder_naam, HUIDIGE_HUURDERS)
    if pad is None:
        return False
    return _run("mkdir", pad)


def upload_bestand(config: Config, pand: Pand, huurder_naam: str, bestandsnaam: str, inhoud: bytes) -> bool:
    """Uploadt (of overschrijft) `bestandsnaam` in de Drive-map van deze
    huurder onder 'Huidige huurders'."""
    pad = _huurder_pad(config, pand, huurder_naam, HUIDIGE_HUURDERS)
    if pad is None:
        return False
    try:
        subprocess.run(
            ["rclone", "rcat", f"{pad}/{bestandsnaam}"],
            input=inhoud, check=True, capture_output=True, timeout=_TIMEOUT_SECONDEN,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("Drive-upload van '%s' voor %s (%s) mislukt: %s", bestandsnaam, huurder_naam, pand.slug, exc)
        return False


def verhuis_naar_oude_huurders(config: Config, pand: Pand, huurder_naam: str) -> bool:
    """Verplaatst de hele Drive-map van een vertrekkende huurder van
    'Huidige huurders' naar 'Oude huurders' (server-side, geen download/
    upload nodig). Doet niets (en faalt stil) als er nog geen mapje voor
    deze huurder bestond - dat kan best, niet elke (oud-)huurder heeft al
    een bestand gehad."""
    van = _huurder_pad(config, pand, huurder_naam, HUIDIGE_HUURDERS)
    naar = _huurder_pad(config, pand, huurder_naam, OUDE_HUURDERS)
    if van is None or naar is None:
        return False
    return _run("moveto", van, naar)


def _run(*args: str) -> bool:
    try:
        subprocess.run(["rclone", *args], check=True, capture_output=True, timeout=_TIMEOUT_SECONDEN)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("rclone-opdracht mislukt (%s): %s", args, exc)
        return False
