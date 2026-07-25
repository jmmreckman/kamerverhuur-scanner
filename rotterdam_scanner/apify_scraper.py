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

Gebruikt bewust de ASYNCHRONE Apify-flow (start de run, poll de status,
haal de dataset pas op zodra de run klaar is) i.p.v. de eenvoudigere
"run-sync-get-dataset-items"-endpoint: die laatste heeft een harde
serverlimiet van 300 seconden, waarna de HTTP-verbinding wordt verbroken -
bij een grote pull (de wekelijkse volledige scan, tot een paar duizend
resultaten) duurt het ophalen vaak langer dan dat, met een afgebroken
("Aborted") en toch betaalde run tot gevolg zonder dat er iets van het
resultaat verwerkt wordt. De asynchrone flow ontkoppelt onze HTTP-
verbinding van de levensduur van de run, dus een trage pull kan gewoon
doorlopen.

Veldnamen in _item_naar_listing() zijn gebaseerd op de gedocumenteerde
output-schema van de easyapi/funda-nl-scraper-actor (juli 2026) - bevestigd
via een echte productie-aanroep. Best-effort: een item met een onherkend
adres wordt overgeslagen (zie _item_naar_listing), niet een fatale fout."""
from __future__ import annotations

import re
import time
from datetime import date

import requests

from .config import Config
from .funda_mail import FundaListing, _maak_object_id

_RUNS_API_URL = "https://api.apify.com/v2/acts/{actor_pad}/runs"
_RUN_STATUS_URL = "https://api.apify.com/v2/actor-runs/{run_id}"
_DATASET_ITEMS_URL = "https://api.apify.com/v2/datasets/{dataset_id}/items"

# Alleen voor het starten van de run resp. het ophalen van de statuscheck -
# niet voor het wachten op de run zelf (dat gebeurt via _poll_tot_klaar()
# met zijn eigen, veel ruimere budget hieronder).
_VERZOEK_TIMEOUT_SECONDEN = 30
_DATASET_TIMEOUT_SECONDEN = 120
_POLL_INTERVAL_SECONDEN = 10
# 25 minuten - ruim genoeg voor de grootste (wekelijkse) pull van een paar
# duizend resultaten; ruimer dan dit zou een hangende run te lang laten
# doorlopen zonder dat de aanroeper (bv. de "Totale sweep"-knop) iets hoort.
_MAX_WACHTTIJD_SECONDEN = 1500
_AFGERONDE_STATUSSEN = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}

_FUNDA_BASIS_URL = "https://www.funda.nl"

_HUISNUMMER_RE = re.compile(r"^(?P<huisnummer>\d+)[\s-]*(?P<toevoeging>[A-Za-z0-9]*)$")


class ApifyError(RuntimeError):
    """Apify is niet (goed) ingesteld, of de aanroep is mislukt."""


def is_ingesteld(config: Config, search_urls: list[str]) -> bool:
    return bool(config.apify_api_token and search_urls)


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


def _start_run(config: Config, search_urls: list[str], max_items: int) -> tuple[str, str]:
    """Start de actor-run asynchroon en geeft (run_id, dataset_id) terug."""
    actor_pad = config.apify_actor_id.replace("/", "~")
    payload = {
        "searchUrls": search_urls,
        "maxItems": max_items,
        "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
    }
    try:
        resp = requests.post(
            _RUNS_API_URL.format(actor_pad=actor_pad),
            params={"token": config.apify_api_token},
            json=payload,
            timeout=_VERZOEK_TIMEOUT_SECONDEN,
        )
        resp.raise_for_status()
        run = resp.json()["data"]
    except requests.RequestException as exc:
        raise ApifyError(f"Apify-run starten mislukt: {exc}") from exc
    except (ValueError, KeyError) as exc:
        raise ApifyError(f"Onverwacht antwoord van Apify bij het starten van de run: {exc}") from exc

    run_id = run.get("id")
    dataset_id = run.get("defaultDatasetId")
    if not run_id or not dataset_id:
        raise ApifyError("Onverwacht antwoord van Apify: geen run-id of dataset-id ontvangen.")
    return run_id, dataset_id


def _poll_tot_klaar(config: Config, run_id: str) -> str:
    """Wacht tot de run een eindstatus heeft (best-effort: geeft die status
    terug, ook als dat niet SUCCEEDED is - de aanroeper bepaalt of dat een
    fout is) of geeft op na _MAX_WACHTTIJD_SECONDEN."""
    verstreken = 0.0
    while verstreken < _MAX_WACHTTIJD_SECONDEN:
        time.sleep(_POLL_INTERVAL_SECONDEN)
        verstreken += _POLL_INTERVAL_SECONDEN
        try:
            resp = requests.get(
                _RUN_STATUS_URL.format(run_id=run_id),
                params={"token": config.apify_api_token},
                timeout=_VERZOEK_TIMEOUT_SECONDEN,
            )
            resp.raise_for_status()
            status = resp.json()["data"]["status"]
        except requests.RequestException as exc:
            raise ApifyError(f"Status opvragen van Apify-run mislukt: {exc}") from exc
        except (ValueError, KeyError) as exc:
            raise ApifyError(f"Onverwacht antwoord van Apify bij statuscheck: {exc}") from exc

        if status in _AFGERONDE_STATUSSEN:
            return status
    raise ApifyError(
        f"Apify-run {run_id} duurt langer dan {_MAX_WACHTTIJD_SECONDEN}s - afgebroken met wachten "
        "(de run zelf loopt gewoon door bij Apify, maar wordt nu niet verwerkt)."
    )


def _haal_dataset_items(config: Config, dataset_id: str) -> list[dict]:
    try:
        resp = requests.get(
            _DATASET_ITEMS_URL.format(dataset_id=dataset_id),
            params={"token": config.apify_api_token, "format": "json"},
            timeout=_DATASET_TIMEOUT_SECONDEN,
        )
        resp.raise_for_status()
        items = resp.json()
    except requests.RequestException as exc:
        raise ApifyError(f"Resultaten ophalen bij Apify mislukt: {exc}") from exc
    except ValueError as exc:
        raise ApifyError(f"Onverwacht antwoord van Apify (geen geldige JSON): {exc}") from exc

    if not isinstance(items, list):
        raise ApifyError(f"Onverwacht antwoord van Apify (geen lijst): {type(items).__name__}")
    return items


def fetch_apify_listings(config: Config, search_urls: list[str], max_items: int) -> list[FundaListing]:
    """Draait de geconfigureerde Apify-actor voor `search_urls` en geeft de
    herkende listings terug (dubbele object_id's, bv. hetzelfde huis via
    meerdere zoek-URL's, worden samengevoegd). `search_urls` komt normaal van
    zoek_urls.laad() - hier expliciet als parameter i.p.v. rechtstreeks uit
    config, zodat de beheerbare lijst (via de website) en de eenmalige
    env-instelling (APIFY_SEARCH_URLS) niet door elkaar hoeven te lopen."""
    if not is_ingesteld(config, search_urls):
        raise ApifyError("APIFY_API_TOKEN en/of de zoek-URL's zijn niet ingesteld.")

    run_id, dataset_id = _start_run(config, search_urls, max_items)
    status = _poll_tot_klaar(config, run_id)
    if status != "SUCCEEDED":
        raise ApifyError(f"Apify-run {run_id} eindigde met status '{status}' i.p.v. SUCCEEDED.")

    items = _haal_dataset_items(config, dataset_id)

    listings: dict[str, FundaListing] = {}
    for item in items:
        listing = _item_naar_listing(item)
        if listing is not None:
            listings[listing.object_id] = listing
    return list(listings.values())
