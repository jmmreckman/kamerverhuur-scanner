"""Bewaart het resultaat van de laatste 'check betalingen'-run per pand in een
klein JSON-bestandje, zodat de website dat kan tonen zonder bij elk
paginabezoek opnieuw bunq/Sheets te hoeven bevragen."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .models import TenantResult


def _bestandsnaam(pand_slug: str, state_dir: str = ".") -> Path:
    veilige_slug = re.sub(r"[^a-z0-9_-]", "-", pand_slug.lower())
    return Path(state_dir) / f"laatste_resultaat_{veilige_slug}.json"


def save(pand_slug: str, results: list[TenantResult], niet_gekoppelde_betalingen: int, state_dir: str = ".") -> None:
    data = {
        "gecontroleerd_op": datetime.now().strftime("%d-%m-%Y %H:%M"),
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
    data[f"{kamer}|{soort}|{maand}"] = datetime.now().strftime("%d-%m-%Y %H:%M")
    p.write_text(json.dumps(data, indent=2))


def email_verzonden_op(pand_slug: str, kamer: str, soort: str, maand: str, state_dir: str = ".") -> str | None:
    p = _verzonden_bestandsnaam(pand_slug, state_dir)
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    return data.get(f"{kamer}|{soort}|{maand}")
