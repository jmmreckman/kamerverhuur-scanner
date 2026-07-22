"""Bewaart het resultaat van de laatste 'check betalingen'-run per pand in een
klein JSON-bestandje, zodat de website dat kan tonen zonder bij elk
paginabezoek opnieuw bunq/Sheets te hoeven bevragen."""
from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
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
    data[f"{kamer}|{einddatum}"] = datetime.now().strftime("%d-%m-%Y %H:%M")
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
    vandaag = datetime.now().strftime("%Y-%m-%d")
    data = [punt for punt in data if punt["datum"] != vandaag]
    data.append({"datum": vandaag, "winst": str(winst)})
    data.sort(key=lambda punt: punt["datum"])
    p.write_text(json.dumps(data, indent=2))


def laad_winst_geschiedenis(pand_slug: str, state_dir: str = ".") -> list[dict]:
    p = _winst_geschiedenis_bestandsnaam(pand_slug, state_dir)
    if not p.exists():
        return []
    return json.loads(p.read_text())
