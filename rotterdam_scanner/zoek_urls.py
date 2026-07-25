"""Beheer van de Apify-zoek-URL's (eigen Funda-zoekopdrachten) - opgeslagen in
een los JSON-bestand naast state.json, zodat ze via de kansen-website beheerd
kunnen worden zonder in fundazoeker.env te hoeven rommelen op de VPS (geen
herstart nodig, ander proces ziet de wijziging bij de eerstvolgende scan).

APIFY_SEARCH_URLS (de omgevingsvariabele, zie config.py) is alleen nog de
initiele vulling voor als dit bestand nog niet bestaat - zodra er via de
website iets gewijzigd is (ook een verwijdering tot een lege lijst), is dit
bestand leidend en wordt de omgevingsvariabele niet meer gebruikt.

Elke zoekopdracht heeft naast de URL ook een optioneel label (bv. "RDAM 100
m2+ <400k") zodat de lijst herkenbaar blijft. Bestanden van vóór deze
labels-feature (een platte lijst van URL-strings) worden bij het laden
automatisch omgezet naar het {"label", "url"}-formaat."""
from __future__ import annotations

import json
from pathlib import Path

from .config import Config


def _pad(config: Config) -> Path:
    return Path(config.state_path).parent / "apify_zoek_urls.json"


def _laad_ruw(config: Config) -> list[dict]:
    pad = _pad(config)
    if not pad.is_file():
        return [{"label": "", "url": url} for url in config.apify_search_urls]
    try:
        ruw = json.loads(pad.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [{"label": "", "url": url} for url in config.apify_search_urls]
    if not isinstance(ruw, list):
        return [{"label": "", "url": url} for url in config.apify_search_urls]

    opdrachten = []
    for item in ruw:
        if isinstance(item, str):
            opdrachten.append({"label": "", "url": item})
        elif isinstance(item, dict) and item.get("url"):
            opdrachten.append({"label": item.get("label") or "", "url": item["url"]})
    return opdrachten


def laad(config: Config) -> list[str]:
    """Alleen de URL's - voor de Apify-scan zelf, die niets met het label doet."""
    return [opdracht["url"] for opdracht in _laad_ruw(config)]


def laad_met_labels(config: Config) -> list[dict]:
    """Voor de beheerpagina: elke zoekopdracht als {"label", "url"}."""
    return _laad_ruw(config)


def _sla_op(config: Config, opdrachten: list[dict]) -> None:
    pad = _pad(config)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(opdrachten, indent=2, ensure_ascii=False), encoding="utf-8")


def voeg_toe(config: Config, url: str, label: str = "") -> list[dict]:
    """Voegt `url` toe met optioneel `label` (geen duplicaten op URL, lege URL
    wordt genegeerd) en geeft de bijgewerkte lijst terug."""
    url = url.strip()
    label = label.strip()
    opdrachten = _laad_ruw(config)
    if url and not any(opdracht["url"] == url for opdracht in opdrachten):
        opdrachten.append({"label": label, "url": url})
        _sla_op(config, opdrachten)
    return opdrachten


def verwijder(config: Config, url: str) -> list[dict]:
    """Haalt de zoekopdracht met deze `url` uit de lijst (indien aanwezig) en
    geeft de bijgewerkte lijst terug."""
    opdrachten = [opdracht for opdracht in _laad_ruw(config) if opdracht["url"] != url]
    _sla_op(config, opdrachten)
    return opdrachten
