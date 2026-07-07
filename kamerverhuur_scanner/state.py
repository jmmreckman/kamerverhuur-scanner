"""Bewaart het resultaat van de laatste 'check betalingen'-run per pand in een
klein JSON-bestandje, zodat de website dat kan tonen zonder bij elk
paginabezoek opnieuw bunq/Sheets te hoeven bevragen."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .models import TenantResult


def _bestandsnaam(pand_slug: str) -> str:
    veilige_slug = re.sub(r"[^a-z0-9_-]", "-", pand_slug.lower())
    return f"laatste_resultaat_{veilige_slug}.json"


def save(pand_slug: str, results: list[TenantResult], niet_gekoppelde_betalingen: int) -> None:
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
    Path(_bestandsnaam(pand_slug)).write_text(json.dumps(data, indent=2))


def load(pand_slug: str) -> dict | None:
    p = Path(_bestandsnaam(pand_slug))
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
