"""Beheer van de Apify-zoek-URL's (eigen Funda-zoekopdrachten) - opgeslagen in
een los JSON-bestand naast state.json, zodat ze via de kansen-website beheerd
kunnen worden zonder in fundazoeker.env te hoeven rommelen op de VPS (geen
herstart nodig, ander proces ziet de wijziging bij de eerstvolgende scan).

APIFY_SEARCH_URLS (de omgevingsvariabele, zie config.py) is alleen nog de
initiele vulling voor als dit bestand nog niet bestaat - zodra er via de
website iets gewijzigd is (ook een verwijdering tot een lege lijst), is dit
bestand leidend en wordt de omgevingsvariabele niet meer gebruikt."""
from __future__ import annotations

import json
from pathlib import Path

from .config import Config


def _pad(config: Config) -> Path:
    return Path(config.state_path).parent / "apify_zoek_urls.json"


def laad(config: Config) -> list[str]:
    pad = _pad(config)
    if not pad.is_file():
        return list(config.apify_search_urls)
    try:
        urls = json.loads(pad.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return list(config.apify_search_urls)
    if not isinstance(urls, list):
        return list(config.apify_search_urls)
    return urls


def _sla_op(config: Config, urls: list[str]) -> None:
    pad = _pad(config)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(urls, indent=2, ensure_ascii=False), encoding="utf-8")


def voeg_toe(config: Config, url: str) -> list[str]:
    """Voegt `url` toe (geen duplicaten, lege waarde wordt genegeerd) en
    geeft de bijgewerkte lijst terug."""
    url = url.strip()
    urls = laad(config)
    if url and url not in urls:
        urls.append(url)
        _sla_op(config, urls)
    return urls


def verwijder(config: Config, url: str) -> list[str]:
    """Haalt `url` uit de lijst (indien aanwezig) en geeft de bijgewerkte
    lijst terug."""
    urls = [u for u in laad(config) if u != url]
    _sla_op(config, urls)
    return urls
