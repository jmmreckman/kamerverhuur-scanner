"""Lokale opslag (op de server zelf, in STATE_DIR) van aanbod-foto's/video's
en bewijsstukken van aanmeldingen - in plaats van Google Drive.

Waarom niet Drive: een Google *service account* (het soort inlog dat deze
site gebruikt) heeft zelf 0 GB opslagruimte. Zodra de site probeert een
bestand te UPLOADEN naar een gewone, persoonlijke Drive-map die alleen met
dat account gedeeld is, weigert Google dat altijd met een
"storageQuotaExceeded"-fout - ongeacht bestandsgrootte. Browsen/downloaden in
de Documenten-module werkt wel (dat kost geen opslag van het account zelf),
maar nieuwe foto's/video's/bewijsstukken uploaden dus niet. Lokale opslag op
de server omzeilt dit probleem volledig.

Bestanden staan onder `<state_dir>/media/<pand-slug>/<categorie>/<kamer>/` -
dezelfde blijvend gekoppelde data-map die ook de betaalcontrole-cache
gebruikt (STATE_DIR=/app/data op de VPS), dus overleeft een herbuild/deploy.
Elk bestand krijgt een willekeurige (uuid) bestandsnaam op schijf, met een
klein .meta-bestand ernaast voor de oorspronkelijke bestandsnaam en het
mimetype.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .models import Pand


@dataclass(frozen=True)
class LokaalBestand:
    id: str  # bestandsnaam op schijf (uuid + originele extensie)
    naam: str  # oorspronkelijke bestandsnaam, voor weergave/download
    mimetype: str
    grootte: int


def _veilig(tekst: str) -> str:
    """Zet een vrije naam (kamer, pand-slug) om naar een veilig mapnaamdeel -
    voorkomt path traversal (bv. "..") en rare tekens in bestandspaden."""
    return re.sub(r"[^a-z0-9_-]+", "-", tekst.lower()).strip("-") or "onbekend"


class LokaleMediaClient:
    def __init__(self, config: Config, pand: Pand, categorie: str):
        """`categorie` is bv. "aanbod" of "aanmeldingen" - houdt de
        mappenstructuur overzichtelijk en voorkomt naamsconflicten tussen
        beide soorten uploads."""
        self._basis = Path(config.state_dir) / "media" / _veilig(pand.slug) / _veilig(categorie)

    def _kamer_map(self, kamer: str, maak_aan: bool = False) -> Path:
        pad = self._basis / _veilig(kamer)
        if maak_aan:
            pad.mkdir(parents=True, exist_ok=True)
        return pad

    def _meta_pad(self, bestand_pad: Path) -> Path:
        return bestand_pad.with_name(bestand_pad.name + ".meta")

    def list_bestanden(self, kamer: str) -> list[LokaalBestand]:
        pad = self._kamer_map(kamer)
        if not pad.is_dir():
            return []
        bestanden = []
        for bestand_pad in sorted(pad.iterdir()):
            if not bestand_pad.is_file() or bestand_pad.suffix == ".meta":
                continue
            meta = self._lees_meta(bestand_pad)
            bestanden.append(
                LokaalBestand(
                    id=bestand_pad.name,
                    naam=meta.get("naam", bestand_pad.name),
                    mimetype=meta.get("mimetype") or "application/octet-stream",
                    grootte=bestand_pad.stat().st_size,
                )
            )
        return bestanden

    def upload_bestand(self, kamer: str, bestandsnaam: str, mimetype: str, inhoud: bytes) -> str:
        pad = self._kamer_map(kamer, maak_aan=True)
        extensie = Path(bestandsnaam).suffix
        bestand_id = f"{uuid.uuid4().hex}{extensie}"
        (pad / bestand_id).write_bytes(inhoud)
        self._schrijf_meta(pad / bestand_id, bestandsnaam, mimetype or "application/octet-stream")
        return bestand_id

    def verwijder_bestand(self, kamer: str, bestand_id: str) -> None:
        bestand_pad = self._kamer_map(kamer) / Path(bestand_id).name  # .name voorkomt path traversal
        bestand_pad.unlink(missing_ok=True)
        self._meta_pad(bestand_pad).unlink(missing_ok=True)

    def lees_bestand(self, kamer: str, bestand_id: str) -> tuple[str, str, bytes] | None:
        """Geeft (bestandsnaam, mimetype, inhoud) terug, of None als het
        bestand niet bestaat."""
        bestand_pad = self._kamer_map(kamer) / Path(bestand_id).name
        if not bestand_pad.is_file():
            return None
        meta = self._lees_meta(bestand_pad)
        naam = meta.get("naam", bestand_pad.name)
        mimetype = meta.get("mimetype") or "application/octet-stream"
        return naam, mimetype, bestand_pad.read_bytes()

    @staticmethod
    def _schrijf_meta(bestand_pad: Path, naam: str, mimetype: str) -> None:
        meta_pad = bestand_pad.with_name(bestand_pad.name + ".meta")
        meta_pad.write_text(json.dumps({"naam": naam, "mimetype": mimetype}))

    @staticmethod
    def _lees_meta(bestand_pad: Path) -> dict:
        meta_pad = bestand_pad.with_name(bestand_pad.name + ".meta")
        if not meta_pad.is_file():
            return {}
        try:
            return json.loads(meta_pad.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
