"""Bladeren door, uploaden naar en downloaden uit de automatisch aangemaakte
"Steenhub <pandnaam>"-Drive-map (zie drive_sync.py), via rclone - voor de
Documenten-pagina in de webapp.

Vervangt de oudere, service-account-gebaseerde aanpak (het inmiddels
verwijderde drive_client.py): dat vereiste een aparte, handmatig gedeelde
Drive-map per pand (google_drive_folder_id in properties.json) - dubbelop
met de map die drive_sync.py toch al automatisch aanmaakt zodra er een
contract getekend wordt of een documentverzoek binnenkomt. Bovendien kon een
service account nooit succesvol uploaden (0 GB eigen opslag,
storageQuotaExceeded), dus werkte "bestand toevoegen" op de oude
Documenten-pagina in de praktijk niet. rclone gebruikt de eigen, echte
Google-login van de gebruiker (dezelfde koppeling als drive_sync.py) en
heeft dat probleem niet.

Navigeren gebeurt op basis van een relatief pad (bv. "Huidige huurders/Jane
Doe") in plaats van Drive-map-ID's - simpeler, en er is geen aparte
kruimelpad-opzoekactie (voorheen meerdere Drive-API-aanroepen na elkaar)
meer voor nodig."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .config import Config
from .drive_sync import pand_root
from .models import Pand

_TIMEOUT_SECONDEN = 60


class DriveBrowseError(RuntimeError):
    """Bladeren/uploaden/downloaden via Drive is mislukt, of nog niet
    ingesteld (RCLONE_REMOTE ontbreekt)."""


@dataclass(frozen=True)
class DriveItem:
    naam: str
    pad: str  # relatief pad t.o.v. de pand-hoofdmap - voor navigeren/downloaden
    is_map: bool
    grootte: int | None
    gewijzigd_op: str
    mimetype: str


def is_ingesteld(config: Config) -> bool:
    return bool(config.rclone_remote)


def _basis(config: Config, pand: Pand) -> str:
    root = pand_root(config, pand)
    if root is None:
        raise DriveBrowseError("Drive-koppeling is niet ingesteld (RCLONE_REMOTE ontbreekt in .env).")
    return root


def _volledig_pad(config: Config, pand: Pand, relatief_pad: str) -> str:
    basis = _basis(config, pand)
    relatief_pad = relatief_pad.strip("/")
    return f"{basis}/{relatief_pad}" if relatief_pad else basis


def list_bestanden(config: Config, pand: Pand, relatief_pad: str = "") -> list[DriveItem]:
    """Alle bestanden/mappen direct onder `relatief_pad`, mappen eerst en dan
    op naam. Een (nog) niet bestaande map (bv. een pand waar nog nooit iets
    voor is weggeschreven) geeft gewoon een lege lijst, geen foutmelding."""
    doel = _volledig_pad(config, pand, relatief_pad)
    try:
        resultaat = subprocess.run(
            ["rclone", "lsjson", doel], capture_output=True, timeout=_TIMEOUT_SECONDEN,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise DriveBrowseError(f"Bladeren door Drive is mislukt: {exc}") from exc
    if resultaat.returncode != 0:
        return []
    try:
        ruw = json.loads(resultaat.stdout or "[]")
    except json.JSONDecodeError:
        return []
    relatief_pad = relatief_pad.strip("/")
    items = [
        DriveItem(
            naam=item["Name"],
            pad=f"{relatief_pad}/{item['Name']}".strip("/"),
            is_map=bool(item.get("IsDir")),
            grootte=None if item.get("IsDir") else item.get("Size"),
            gewijzigd_op=(item.get("ModTime") or "")[:10],
            mimetype=item.get("MimeType") or "",
        )
        for item in ruw
    ]
    items.sort(key=lambda i: (not i.is_map, i.naam.lower()))
    return items


def lees_bestand(config: Config, pand: Pand, relatief_pad: str) -> bytes:
    doel = _volledig_pad(config, pand, relatief_pad)
    try:
        resultaat = subprocess.run(
            ["rclone", "cat", doel], capture_output=True, timeout=_TIMEOUT_SECONDEN,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise DriveBrowseError(f"Downloaden is mislukt: {exc}") from exc
    if resultaat.returncode != 0:
        raise DriveBrowseError("Bestand niet gevonden.")
    return resultaat.stdout


def upload_bestand(config: Config, pand: Pand, relatief_map_pad: str, bestandsnaam: str, inhoud: bytes) -> None:
    doel = _volledig_pad(config, pand, relatief_map_pad)
    try:
        subprocess.run(
            ["rclone", "rcat", f"{doel}/{bestandsnaam}"],
            input=inhoud, check=True, capture_output=True, timeout=_TIMEOUT_SECONDEN,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise DriveBrowseError(f"Uploaden is mislukt: {exc}") from exc


def maak_map(config: Config, pand: Pand, relatief_map_pad: str, naam: str) -> None:
    doel = _volledig_pad(config, pand, relatief_map_pad)
    try:
        subprocess.run(
            ["rclone", "mkdir", f"{doel}/{naam}"], check=True, capture_output=True, timeout=_TIMEOUT_SECONDEN,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise DriveBrowseError(f"Map aanmaken is mislukt: {exc}") from exc
