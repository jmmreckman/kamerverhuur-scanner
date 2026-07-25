"""Tests voor het ophalen van het Funda-aanbod via Apify - de echte Apify-API
wordt hier nooit aangeroepen, alleen requests.post/get gemockt (en
time.sleep, zodat de polling-tests niet echt hoeven te wachten). Het
voorbeeld-item is gebaseerd op de gedocumenteerde output van de
easyapi/funda-nl-scraper-actor (juli 2026), bevestigd tegen een echte
productie-aanroep."""
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

_RUN_ID = "abc123"
_DATASET_ID = "dataset456"


def _config(**overrides):
    defaults = dict(
        gmail_address="scanner@example.com", gmail_app_password="x", report_to=["x@example.com"],
        funda_mail_folder="INBOX", listing_expiry_days=30, opkoopbescherming_woz_grens=470_000,
        apify_api_token="apify-token", apify_search_urls=["https://www.funda.nl/koop/rotterdam/"],
    )
    defaults.update(overrides)
    return Config(**defaults)


_URLS = ["https://www.funda.nl/koop/rotterdam/"]


def _start_resp(status="SUCCEEDED"):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"data": {"id": _RUN_ID, "defaultDatasetId": _DATASET_ID, "status": status}}
    return resp


def _status_resp(status):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"data": {"status": status}}
    return resp


def _items_resp(items):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = items
    return resp


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


# --- fetch_apify_listings (asynchrone flow: start run -> poll -> dataset) ---


def test_fetch_apify_listings_zonder_token_geeft_apify_error():
    with pytest.raises(ApifyError):
        apify_scraper.fetch_apify_listings(_config(apify_api_token=""), _URLS, max_items=100)


def test_fetch_apify_listings_zonder_search_urls_geeft_apify_error():
    with pytest.raises(ApifyError):
        apify_scraper.fetch_apify_listings(_config(), [], max_items=100)


def test_fetch_apify_listings_bouwt_juiste_start_aanroep_en_haalt_resultaat_op():
    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=_start_resp("SUCCEEDED")) as mock_post, \
         patch("rotterdam_scanner.apify_scraper.time.sleep"), \
         patch(
             "rotterdam_scanner.apify_scraper.requests.get",
             side_effect=[_status_resp("SUCCEEDED"), _items_resp([_VOORBEELD_ITEM])],
         ) as mock_get:
        listings = apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)

    assert len(listings) == 1
    assert listings[0].object_id == "5854PC-38"

    kwargs = mock_post.call_args.kwargs
    assert kwargs["params"] == {"token": "apify-token"}
    assert kwargs["json"]["searchUrls"] == ["https://www.funda.nl/koop/rotterdam/"]
    assert kwargs["json"]["maxItems"] == 150
    assert kwargs["json"]["proxyConfiguration"]["useApifyProxy"] is True
    assert "acts/easyapi~funda-nl-scraper/runs" in mock_post.call_args.args[0]

    dataset_kwargs = mock_get.call_args.kwargs
    assert dataset_kwargs["params"]["token"] == "apify-token"
    assert f"datasets/{_DATASET_ID}/items" in mock_get.call_args.args[0]


def test_fetch_apify_listings_gebruikt_meegegeven_search_urls_niet_config():
    andere_urls = ["https://www.funda.nl/koop/hoek-van-holland/"]
    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=_start_resp("SUCCEEDED")) as mock_post, \
         patch("rotterdam_scanner.apify_scraper.time.sleep"), \
         patch(
             "rotterdam_scanner.apify_scraper.requests.get",
             side_effect=[_status_resp("SUCCEEDED"), _items_resp([])],
         ):
        apify_scraper.fetch_apify_listings(_config(), andere_urls, max_items=150)
    assert mock_post.call_args.kwargs["json"]["searchUrls"] == andere_urls


def test_fetch_apify_listings_dedupt_op_object_id():
    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=_start_resp("SUCCEEDED")), \
         patch("rotterdam_scanner.apify_scraper.time.sleep"), \
         patch(
             "rotterdam_scanner.apify_scraper.requests.get",
             side_effect=[_status_resp("SUCCEEDED"), _items_resp([_VOORBEELD_ITEM, dict(_VOORBEELD_ITEM)])],
         ):
        listings = apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)
    assert len(listings) == 1


def test_fetch_apify_listings_slaat_onherkende_items_over():
    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=_start_resp("SUCCEEDED")), \
         patch("rotterdam_scanner.apify_scraper.time.sleep"), \
         patch(
             "rotterdam_scanner.apify_scraper.requests.get",
             side_effect=[_status_resp("SUCCEEDED"), _items_resp([_VOORBEELD_ITEM, {"address": {}}])],
         ):
        listings = apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)
    assert len(listings) == 1


def test_fetch_apify_listings_netwerkfout_bij_starten_geeft_apify_error():
    import requests as requests_module

    with patch("rotterdam_scanner.apify_scraper.requests.post", side_effect=requests_module.ConnectionError("boom")):
        with pytest.raises(ApifyError):
            apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)


def test_fetch_apify_listings_geen_run_of_dataset_id_geeft_apify_error():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"data": {"status": "READY"}}  # geen id/defaultDatasetId
    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=resp):
        with pytest.raises(ApifyError):
            apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)


def test_fetch_apify_listings_pollt_tot_eindstatus():
    status_responses = [_status_resp("RUNNING"), _status_resp("RUNNING"), _status_resp("SUCCEEDED")]
    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=_start_resp("READY")), \
         patch("rotterdam_scanner.apify_scraper.time.sleep") as mock_sleep, \
         patch("rotterdam_scanner.apify_scraper.requests.get", side_effect=status_responses + [_items_resp([])]) as mock_get:
        listings = apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)

    assert listings == []
    assert mock_sleep.call_count == 3  # 1x per statuscheck, ook de laatste (SUCCEEDED)
    assert mock_get.call_count == 4  # 3x status + 1x dataset


def test_fetch_apify_listings_mislukte_run_status_geeft_apify_error():
    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=_start_resp("READY")), \
         patch("rotterdam_scanner.apify_scraper.time.sleep"), \
         patch("rotterdam_scanner.apify_scraper.requests.get", return_value=_status_resp("FAILED")):
        with pytest.raises(ApifyError, match="FAILED"):
            apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)


def test_fetch_apify_listings_aborted_status_geeft_apify_error():
    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=_start_resp("READY")), \
         patch("rotterdam_scanner.apify_scraper.time.sleep"), \
         patch("rotterdam_scanner.apify_scraper.requests.get", return_value=_status_resp("ABORTED")):
        with pytest.raises(ApifyError, match="ABORTED"):
            apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)


def test_fetch_apify_listings_polling_geeft_op_na_max_wachttijd():
    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=_start_resp("READY")), \
         patch("rotterdam_scanner.apify_scraper.time.sleep"), \
         patch("rotterdam_scanner.apify_scraper.requests.get", return_value=_status_resp("RUNNING")):
        with pytest.raises(ApifyError, match="afgebroken met wachten"):
            apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)


def test_fetch_apify_listings_netwerkfout_bij_statuscheck_geeft_apify_error():
    import requests as requests_module

    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=_start_resp("READY")), \
         patch("rotterdam_scanner.apify_scraper.time.sleep"), \
         patch(
             "rotterdam_scanner.apify_scraper.requests.get",
             side_effect=requests_module.ConnectionError("boom"),
         ):
        with pytest.raises(ApifyError):
            apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)


def test_fetch_apify_listings_netwerkfout_bij_dataset_ophalen_geeft_apify_error():
    import requests as requests_module

    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=_start_resp("SUCCEEDED")), \
         patch("rotterdam_scanner.apify_scraper.time.sleep"), \
         patch(
             "rotterdam_scanner.apify_scraper.requests.get",
             side_effect=requests_module.ConnectionError("boom"),
         ):
        with pytest.raises(ApifyError):
            apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)


def test_fetch_apify_listings_geen_lijst_geeft_apify_error():
    with patch("rotterdam_scanner.apify_scraper.requests.post", return_value=_start_resp("SUCCEEDED")), \
         patch("rotterdam_scanner.apify_scraper.time.sleep"), \
         patch(
             "rotterdam_scanner.apify_scraper.requests.get",
             side_effect=[_status_resp("SUCCEEDED"), _items_resp({"error": "iets ging mis"})],
         ):
        with pytest.raises(ApifyError):
            apify_scraper.fetch_apify_listings(_config(), _URLS, max_items=150)
