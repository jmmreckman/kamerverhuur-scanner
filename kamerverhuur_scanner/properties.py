"""Laadt de lijst van panden (properties.json) - elk pand heeft zijn eigen
Google Sheet, Drive-map en bunq-rekening, maar deelt dezelfde service account
en bunq-koppeling met de andere panden."""
from __future__ import annotations

import json
from pathlib import Path

from .models import Pand, Verhuurder


class PropertiesError(RuntimeError):
    pass


def _normaliseer_extra_bcc(waarde) -> list[str]:
    """extra_bcc mag in properties.json een lijst zijn (normale vorm, zoals
    zet_pand 'm opslaat) of - bij handmatig bewerken - een komma-gescheiden
    string."""
    if not waarde:
        return []
    if isinstance(waarde, str):
        return [e.strip() for e in waarde.split(",") if e.strip()]
    return [str(e).strip() for e in waarde if str(e).strip()]


def _parse_verhuurders(waarde) -> list[Verhuurder]:
    """verhuurders mag in properties.json een lijst met {'naam', 'adres'}-
    dicts zijn (normale vorm, zoals zet_pand 'm opslaat) of - bij handmatig
    bewerken - een string met per regel "Naam | Adres"."""
    if not waarde:
        return []
    regels = waarde.splitlines() if isinstance(waarde, str) else waarde

    verhuurders = []
    for regel in regels:
        if isinstance(regel, dict):
            naam = str(regel.get("naam", "")).strip()
            adres = str(regel.get("adres", "")).strip()
            if naam:
                verhuurders.append(Verhuurder(naam=naam, adres=adres))
            continue
        tekst = str(regel).strip()
        if not tekst:
            continue
        if "|" in tekst:
            naam, adres = tekst.split("|", 1)
            verhuurders.append(Verhuurder(naam=naam.strip(), adres=adres.strip()))
        else:
            verhuurders.append(Verhuurder(naam=tekst, adres=""))
    return verhuurders


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
                    extra_bcc=_normaliseer_extra_bcc(item.get("extra_bcc")),
                    postcode=item.get("postcode", ""),
                    plaats=item.get("plaats", ""),
                    verhuurders=_parse_verhuurders(item.get("verhuurders")),
                    rekeninghouder_naam=item.get("rekeninghouder_naam", ""),
                    gedeelde_ruimtes=item.get("gedeelde_ruimtes", ""),
                    bijzondere_bepalingen=item.get("bijzondere_bepalingen", ""),
                    gemeente_meldpunt=item.get("gemeente_meldpunt", ""),
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
