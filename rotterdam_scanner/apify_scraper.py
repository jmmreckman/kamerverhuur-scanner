"""Haalt het actuele Funda-aanbod op via een betaalde Apify-actor - in
tegenstelling tot funda_mail.py (dat alleen de eigen dagelijkse mail-alert
leest, dus alleen NIEUWE woningen sinds gisteren) dekt dit ook woningen die
al te koop stonden voordat de zoekopdracht werd ingesteld, en (bij een
volledige scan, zie pipeline.run_apify_volledig()) het complete aanbod.

Waarom niet zelf scrapen? Funda draait achter actieve bot-detectie (zie ook
gis.py/README) - een eigen scraper zou voortdurend onderhoud vragen om
blokkades te omzeilen (proxies, browser-fingerprinting, CAPTCHA's). Apify
beheert dat zelf en rekent per opgehaald resultaat, geen vast maandbedrag.

APIFY_SEARCH_URLS zijn zelf op funda.nl samengestelde zoek-URL's (net als de
bestaande e-mail-zoekopdracht - Koop, Huis, Rotterdam + randgemeentes,
gewoon de URL uit de adresbalk gekopieerd) - dit programma bouwt zelf geen
zoekquery op, dus geen aparte 'gemeente'-instelling hier nodig.

Veldnamen in _item_naar_listing() zijn gebaseerd op de gedocumenteerde
output-schema van de easyapi/funda-nl-scraper-actor (juli 2026) - nog niet
geverifieerd tegen een echte API-aanroep (dat kan pas met een echt
APIFY_API_TOKEN). Best-effort: een item met een onherkend adres wordt
overgeslagen (zie _item_naar_listing), niet een fatale fout."""
from __future__ import annotations

import re
from datetime import date

import requests

from .config import Config
from .funda_mail import FundaListing, _maak_object_id

_API_URL = "https://api.apify.com/v2/acts/{actor_pad}/run-sync-get-dataset-items"
# Een volledige (wekelijkse) scan van een paar duizend woningen kan een paar
# minuten duren - ruim bemeten timeout.
_TIMEOUT_SECONDEN = 300
_FUNDA_BASIS_URL = "https://www.funda.nl"

_HUISNUMMER_RE = re.compile(r"^(?P<huisnummer>\d+)[\s-]*(?P<toevoeging>[A-Za-z0-9]*)$")


class ApifyError(RuntimeError):
    """Apify is niet (goed) ingesteld, of de aanroep is mislukt."""


def is_ingesteld(config: Config) -> bool:
    return bool(config.apify_api_token and config.apify_search_urls)


def _split_huisnummer(ruw: str) -> tuple[str, str]:
    """"38" -> ("38", ""), "38A" / "38-A" / "38 A" -> ("38", "A")."""
    match = _HUISNUMMER_RE.match((ruw or "").strip())
    if not match:
        return ruw or "", ""
    return match.group("huisnummer"), match.group("toevoeging").upper()


def _item_naar_listing(item: dict) -> FundaListing | None:
    """Zet één ruw Apify-dataset-item om naar een FundaListing. Geeft None
    terug (i.p.v. een fout te gooien) bij een item zonder bruikbaar adres of
    URL, zodat één rare listing de rest van de batch niet laat mislukken."""
    adres = item.get("address") or {}
    postcode = (adres.get("postal_code") or "").replace(" ", "").upper() or None
    huisnummer, toevoeging = _split_huisnummer(str(adres.get("house_number") or ""))
    object_id = _maak_object_id(postcode, huisnummer, toevoeging)
    if object_id is None:
        return None

    relatieve_url = item.get("object_detail_page_relative_url") or ""
    if not relatieve_url:
        return None
    url = f"{_FUNDA_BASIS_URL}{relatieve_url}"

    prijs_lijst = (item.get("price") or {}).get("selling_price") or []
    prijs = int(prijs_lijst[0]) if prijs_lijst else None

    oppervlakte_lijst = item.get("floor_area") or []
    oppervlakte = int(oppervlakte_lijst[0]) if oppervlakte_lijst else None

    eerst_gezien = None
    publish_date = item.get("publish_date")
    if publish_date:
        try:
            eerst_gezien = date.fromisoformat(str(publish_date)[:10])
        except ValueError:
            eerst_gezien = None

    return FundaListing(
        object_id=object_id,
        url=url,
        straatnaam=adres.get("street_name") or None,
        huisnummer=huisnummer or None,
        toevoeging=toevoeging,
        postcode=postcode,
        woonplaats=adres.get("city") or None,
        prijs=prijs,
        oppervlakte_advertentie=oppervlakte,
        eerst_gezien_override=eerst_gezien,
    )


def fetch_apify_listings(config: Config, max_items: int) -> list[FundaListing]:
    """Draait de geconfigureerde Apify-actor synchroon en geeft de herkende
    listings terug (dubbele object_id's, bv. hetzelfde huis via meerdere
    zoek-URL's, worden samengevoegd)."""
    if not is_ingesteld(config):
        raise ApifyError("APIFY_API_TOKEN en/of APIFY_SEARCH_URLS zijn niet ingesteld.")

    actor_pad = config.apify_actor_id.replace("/", "~")
    payload = {
        "searchUrls": config.apify_search_urls,
        "maxItems": max_items,
        "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
    }
    try:
        resp = requests.post(
            _API_URL.format(actor_pad=actor_pad),
            params={"token": config.apify_api_token},
            json=payload,
            timeout=_TIMEOUT_SECONDEN,
        )
        resp.raise_for_status()
        items = resp.json()
    except requests.RequestException as exc:
        raise ApifyError(f"Apify-aanroep mislukt: {exc}") from exc
    except ValueError as exc:
        raise ApifyError(f"Onverwacht antwoord van Apify (geen geldige JSON): {exc}") from exc

    if not isinstance(items, list):
        raise ApifyError(f"Onverwacht antwoord van Apify (geen lijst): {type(items).__name__}")

    listings: dict[str, FundaListing] = {}
    for item in items:
        listing = _item_naar_listing(item)
        if listing is not None:
            listings[listing.object_id] = listing
    return list(listings.values())
