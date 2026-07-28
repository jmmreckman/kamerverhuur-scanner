"""Beheer van de browsergebaseerde Funda-zoekopdrachten (zie browser_scraper.py) -
opgeslagen in een los JSON-bestand naast state.json, zodat ze via de kansen-website
beheerd kunnen worden zonder in fundazoeker.env te hoeven rommelen op de VPS (geen
herstart nodig, ander proces ziet de wijziging bij de eerstvolgende scan).

Zelfde opzet als de vroegere Apify-zoek-URL's (rotterdam_scanner/zoek_urls.py, sinds
verwijderd samen met Apify) - elke zoekopdracht heeft een optioneel label (bv.
"Rotterdam t/m 8 ton, 75m2+") zodat de lijst herkenbaar blijft."""
from __future__ import annotations

import json
from pathlib import Path

from .config import Config


def _pad(config: Config) -> Path:
    return Path(config.state_path).parent / "browser_zoek_urls.json"


def _laad_ruw(config: Config) -> list[dict]:
    pad = _pad(config)
    if not pad.is_file():
        return []
    try:
        ruw = json.loads(pad.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(ruw, list):
        return []

    opdrachten = []
    for item in ruw:
        if isinstance(item, dict) and item.get("url"):
            opdrachten.append({"label": item.get("label") or "", "url": item["url"]})
    return opdrachten


def laad(config: Config) -> list[str]:
    """Alleen de URL's - voor de scan zelf, die niets met het label doet."""
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
