"""Laadt de lijst van panden (properties.json) - elk pand heeft zijn eigen
Google Sheet, Drive-map en bunq-rekening, maar deelt dezelfde service account
en bunq-koppeling met de andere panden."""
from __future__ import annotations

import json
from pathlib import Path

from .models import Pand


class PropertiesError(RuntimeError):
    pass


def load_properties(path: str) -> list[Pand]:
    file_path = Path(path)
    if not file_path.exists():
        raise PropertiesError(
            f"Pandenbestand '{path}' niet gevonden. Kopieer properties.json.example naar "
            f"'{path}' en vul je pand(en) in."
        )
    try:
        raw = json.loads(file_path.read_text())
    except json.JSONDecodeError as exc:
        raise PropertiesError(f"'{path}' bevat geen geldige JSON: {exc}") from exc

    if not isinstance(raw, list) or not raw:
        raise PropertiesError(f"'{path}' moet een niet-lege lijst met panden bevatten.")

    panden = []
    for i, item in enumerate(raw):
        try:
            panden.append(
                Pand(
                    slug=item["slug"],
                    naam=item["naam"],
                    google_sheet_id=item["google_sheet_id"],
                    google_sheet_worksheet=item.get("google_sheet_worksheet", "Huurders"),
                    history_worksheet=item.get("history_worksheet", "Historie"),
                    google_drive_folder_id=item.get("google_drive_folder_id") or None,
                    bunq_rekening_iban=item["bunq_rekening_iban"].replace(" ", "").upper(),
                    aanmeldingen_worksheet=item.get("aanmeldingen_worksheet", "Aanmeldingen"),
                )
            )
        except KeyError as exc:
            raise PropertiesError(f"Pand #{i + 1} in '{path}' mist verplicht veld {exc}.") from exc

    slugs = [p.slug for p in panden]
    if len(slugs) != len(set(slugs)):
        raise PropertiesError(f"'{path}' bevat dubbele 'slug'-waarden: {slugs}")

    return panden


def find_pand(panden: list[Pand], slug: str) -> Pand | None:
    return next((p for p in panden if p.slug == slug), None)


def _lees_raw(path: str) -> list[dict]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        raw = json.loads(file_path.read_text())
    except json.JSONDecodeError:
        return []
    return raw if isinstance(raw, list) else []


def zet_pand(path: str, slug: str, gegevens: dict) -> None:
    """Voegt een pand toe of werkt 'm bij (op basis van slug) in properties.json."""
    panden = _lees_raw(path)
    nieuw = {"slug": slug, **gegevens}
    for i, p in enumerate(panden):
        if p.get("slug") == slug:
            panden[i] = nieuw
            break
    else:
        panden.append(nieuw)
    Path(path).write_text(json.dumps(panden, indent=2))


def verwijder_pand(path: str, slug: str) -> None:
    panden = [p for p in _lees_raw(path) if p.get("slug") != slug]
    Path(path).write_text(json.dumps(panden, indent=2))
