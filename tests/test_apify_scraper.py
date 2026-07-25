"""Tests voor het ophalen van het Funda-aanbod via Apify - de echte Apify-API
wordt hier nooit aangeroepen, alleen requests.post gemockt. Het voorbeeld-item
is gebaseerd op de gedocumenteerde output van de easyapi/funda-nl-scraper-
actor (juli 2026)."""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from rotterdam_scanner import apify_scraper
from rotterdam_scanner.apify_scraper import ApifyError
from rotterdam_scanner.config import Config

_VOORBEELD_ITEM = {
    "id": 7332972,
    "globalId": 7332972,
    "address": {
        "street_name": "Siebengewaldseweg",
        "house_number": "38",
        "postal_code": "5854PC",
        "city": "Bergen (LI)",
        "municipality": "Bergen (LI)",
        "province": "Limburg",
        "wijk": "Nieuw-Bergen",
    },
    "price": {"selling_price": [499000], "selling_price_type": "regular"},
    "floor_area": [125],
    "plot_area": [456],
    "object_type": "house",
    "object_detail_page_relative_url": "/detail/koop/bergen-li/huis-siebengewaldseweg-38/43787335/",
    "publish_date": "2024-10-25T15:15:02.5130000",
}


def _config(**overrides):
    defaults = dict(
        gmail_address="scanner@example.com", gmail_app_password="x", report_to=["x@example.com"],
        funda_mail_folder="INBOX", listing_expiry_days=30, opkoopbescherming_woz_grens=470_000,
        apify_api_token="apify-token", apify_search_urls=["https://www.funda.nl/koop/rotterdam/"],
    )
    defaults.update(overrides)
    return Config(**defaults)


_URLS = ["https://www.funda.nl/koop/rotterdam/"]


# --- is_ingesteld ---


def test_is_ingesteld_met_token_en_urls():
    assert apify_scraper.is_ingesteld(_config(), _URLS) is True


def test_niet_ingesteld_zonder_token():
    assert apify_scraper.is_ingesteld(_config(apify_api_token=""), _URLS) is False


def test_niet_ingesteld_zonder_search_urls():
    assert apify_scraper.is_ingesteld(_config(), []) is False


# --- _split_huisnummer ---


@pytest.mark.parametrize("ruw,verwacht", [
    ("38", ("38", "")),
    ("38A", ("38", "A")),
    ("38-A", ("38", "A")),
    ("38 A", ("38", "A")),
    ("38-02", ("38", "02")),
])
def test_split_huisnummer(ruw, verwacht):
    assert apify_scraper._split_huisnummer(ruw) == verwacht


# --- _item_naar_listing ---


def test_item_naar_listing_herkent_alle_velden():
    listing = apify_scraper._item_naar_listing(_VOORBEELD_ITEM)
    assert listing is not None
    assert listing.object_id == "5854PC-38"
    assert listing.url == "https://www.funda.nl/detail/koop/bergen-li/huis-siebengewaldseweg-38/43787335/"
    assert listing.straatnaam == "Siebengewaldseweg"
    assert listing.huisnummer == "38"
    assert listing.toevoeging == ""
    assert listing.postcode == "5854PC"
    assert listing.woonplaats == "Bergen (LI)"
    assert listing.prijs == 499000
    assert listing.oppervlakte_advertentie == 125
    assert listing.eerst_gezien_override == date(2024, 10, 25)


def test_item_zonder_postcode_wordt_overgeslagen():
    item = {**_VOORBEELD_ITEM, "address": {**_VOORBEELD_ITEM["address"], "postal_code": ""}}
    assert apify_scraper._item_naar_listing(item) is None


def test_item_zonder_relatieve_url_wordt_overgeslagen():
    item = {**_VOORBEELD_ITEM, "object_detail_page_relative_url": ""}
    assert apify_scraper._item_naar_listing(item) is None


def test_item_zonder_prijs_geeft_none_prijs():
    item = {**_VOORBEELD_ITEM, "price": {}}
    listing = apify_scraper._item_naar_listing(item)
    assert listing.prijs is None


def test_item_met_ongeldige_publish_date_negeert_datum_zonder_te_crashen():
    item = {**_VOORBEELD_ITEM, "publish_date": "niet-een-datum"}
    listing = apify_scraper._item_naar_listing(item)
    assert listing.eerst_gezien_override is None


def test_item_met_toevoeging_in_huisnummer():
    item = {**_VOORBEELD_ITEM, "address": {**_VOORBEELD_ITEM["address"], "house_number": "38-A"}}
    listing = apify_scraper._item_naar_listing(item)
    assert listing.huisnummer == "38"
    assert listing.toevoeging == "A"
    assert listing.object_id == "5854PC-38A"


# --- fetch_apify_listings ---


def test_fetch_apify_listings_zonder_token_geeft_apify_error():
    with pytest.raises(ApifyError):
        apify_scraper.fetch_apify_listings(_config(apify_api_token=""), _URLS, max_items=100)


def test_fetch_apify_listings_zonder_search_urls_geeft_apify_error():
    with pytest.raises(ApifyError):
        apify_scraper.fetch_apify_listings(_config(), [], max_items=100)


def test_fetch_apify_listings_bouwt_juiste_aanroep():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [_VOORBEELD_ITEM]

    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=mock_resp) as mock_post:
        listings = apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)

    assert len(listings) == 1
    assert listings[0].object_id == "5854PC-38"

    kwargs = mock_post.call_args.kwargs
    assert kwargs["params"] == {"token": "apify-token"}
    assert kwargs["json"]["searchUrls"] == ["https://www.funda.nl/koop/rotterdam/"]
    assert kwargs["json"]["maxItems"] == 150
    assert kwargs["json"]["proxyConfiguration"]["useApifyProxy"] is True
    assert "acts/easyapi~funda-nl-scraper/run-sync-get-dataset-items" in mock_post.call_args.args[0]


def test_fetch_apify_listings_gebruikt_meegegeven_search_urls_niet_config():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = []

    andere_urls = ["https://www.funda.nl/koop/hoek-van-holland/"]
    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=mock_resp) as mock_post:
        apify_scraper.fetch_apify_listings(_config(), andere_urls, max_items=150)
    assert mock_post.call_args.kwargs["json"]["searchUrls"] == andere_urls


def test_fetch_apify_listings_dedupt_op_object_id():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [_VOORBEELD_ITEM, dict(_VOORBEELD_ITEM)]

    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=mock_resp):
        listings = apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)
    assert len(listings) == 1


def test_fetch_apify_listings_slaat_onherkende_items_over():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [_VOORBEELD_ITEM, {"address": {}}]

    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=mock_resp):
        listings = apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)
    assert len(listings) == 1


def test_fetch_apify_listings_netwerkfout_geeft_apify_error():
    import requests as requests_module

    with patch("rotterdam_scanner.apify_scraper.requests.post", side_effect=requests_module.ConnectionError("boom")):
        with pytest.raises(ApifyError):
            apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)


def test_fetch_apify_listings_geen_lijst_geeft_apify_error():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"error": "iets ging mis"}

    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=mock_resp):
        with pytest.raises(ApifyError):
            apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)
