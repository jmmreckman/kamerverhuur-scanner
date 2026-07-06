"""Bewaart het resultaat van de laatste 'check betalingen'-run in een klein
JSON-bestandje, zodat de website dat kan tonen zonder bij elk paginabezoek
opnieuw bunq/Sheets te hoeven bevragen."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import TenantResult

DEFAULT_PATH = "laatste_resultaat.json"


def save(results: list[TenantResult], niet_gekoppelde_betalingen: int, path: str = DEFAULT_PATH) -> None:
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
    Path(path).write_text(json.dumps(data, indent=2))


def load(path: str = DEFAULT_PATH) -> dict | None:
    p = Path(path)
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
