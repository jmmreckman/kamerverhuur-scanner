from unittest.mock import MagicMock, patch

import pytest

from rotterdam_scanner import gis


@pytest.fixture(autouse=True)
def _clear_layer_cache(monkeypatch):
    monkeypatch.delenv(gis.ENV_OVERRIDE, raising=False)
    gis.resolve_layer_urls.cache_clear()
    gis._LAATSTE_STATUS = None
    yield
    gis.resolve_layer_urls.cache_clear()
    gis._LAATSTE_STATUS = None


WEBMAP_RESPONSE = {
    "operationalLayers": [
        {
            "title": "Verleende vergunning kamerverhuur",
            "url": "https://services.arcgis.com/x/arcgis/rest/services/Update_Test/FeatureServer/77",
        },
        {
            "title": "Nulquotum gebieden",
            "url": "https://services.arcgis.com/x/arcgis/rest/services/Nulquotum_test/FeatureServer/0",
        },
    ]
}


def _mock_response(payload):
    mock = MagicMock()
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


def _html_response(text):
    mock = MagicMock()
    mock.text = text
    mock.raise_for_status.return_value = None
    return mock


NIEUW_WEBMAP_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
EXPERIENCE_ID = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_resolve_layer_urls_vindt_beide_lagen():
    with patch("rotterdam_scanner.gis.requests.get", return_value=_mock_response(WEBMAP_RESPONSE)):
        urls = gis.resolve_layer_urls()
    assert "Update_Test" in urls.kamerverhuurvergunning_url
    assert "Nulquotum_test" in urls.nulquotum_url


def test_resolve_layer_urls_faalt_duidelijk_als_laag_ontbreekt():
    with patch("rotterdam_scanner.gis.requests.get", return_value=_mock_response({"operationalLayers": []})):
        with pytest.raises(gis.GisLayerNotFoundError):
            gis.resolve_layer_urls()


def test_point_intersects_true_bij_features():
    with patch(
        "rotterdam_scanner.gis.requests.get",
        return_value=_mock_response({"features": [{"attributes": {"OBJECTID": 1}}]}),
    ):
        assert gis._point_intersects("https://example.com/layer", 1.0, 2.0) is True


def test_point_intersects_false_zonder_features():
    with patch("rotterdam_scanner.gis.requests.get", return_value=_mock_response({"features": []})):
        assert gis._point_intersects("https://example.com/layer", 1.0, 2.0) is False


def test_point_intersects_geeft_arcgis_fout_door():
    with patch(
        "rotterdam_scanner.gis.requests.get",
        return_value=_mock_response({"error": {"code": 400, "message": "kapot"}}),
    ):
        with pytest.raises(RuntimeError):
            gis._point_intersects("https://example.com/layer", 1.0, 2.0)


def test_dynamische_webmap_via_landingspagina():
    """Landingspagina -> experience-app -> onderliggende (nieuwe) webmap: de scanner
    gaat automatisch mee en waarschuwt dat de fallback bijgewerkt moet worden."""
    landing_html = (
        '<a href="https://experience.arcgis.com/experience/'
        f'{EXPERIENCE_ID}">kaart Kamerverhuur</a>'
    )
    exp_data = {"dataSources": {"ds1": {"type": "WEB_MAP", "itemId": NIEUW_WEBMAP_ID}}}

    def fake_get(url, params=None, timeout=None, headers=None):
        if url == gis.LANDINGSPAGINA_URL:
            return _html_response(landing_html)
        if url.endswith("/data"):
            if EXPERIENCE_ID in url:
                return _mock_response(exp_data)
            return _mock_response(WEBMAP_RESPONSE)  # de webmap zelf
        # item-info calls
        if EXPERIENCE_ID in url:
            return _mock_response({"type": "Web Experience"})
        return _mock_response({"type": "Web Map"})

    with patch("rotterdam_scanner.gis.requests.get", side_effect=fake_get):
        urls = gis.resolve_layer_urls()

    assert "Update_Test" in urls.kamerverhuurvergunning_url
    status = gis.kaartbron_status()
    assert status.bron == "landingspagina"
    assert status.webmap_item_id == NIEUW_WEBMAP_ID
    assert any("nieuwe kamerverhuur-webmap" in w for w in status.waarschuwingen)


def test_fallback_bij_onvindbare_kaart_op_landingspagina():
    """Geen bruikbare kaartlink op de landingspagina -> terugval op de laatst
    bekende webmap, mét waarschuwing in de status (en dus in het dagrapport)."""

    def fake_get(url, params=None, timeout=None, headers=None):
        if url == gis.LANDINGSPAGINA_URL:
            return _html_response("<p>Geen kaartknop hier</p>")
        if url.endswith("/data"):
            return _mock_response(WEBMAP_RESPONSE)  # fallback-webmap
        return _mock_response({"type": "Web Map"})

    with patch("rotterdam_scanner.gis.requests.get", side_effect=fake_get):
        urls = gis.resolve_layer_urls()

    assert "Nulquotum_test" in urls.nulquotum_url
    status = gis.kaartbron_status()
    assert status.bron == "fallback"
    assert status.webmap_item_id == gis.FALLBACK_WEBMAP_ITEM_ID
    assert any("laatst bekende webmap" in w for w in status.waarschuwingen)


def test_env_override_wint_en_zonder_waarschuwing(monkeypatch):
    monkeypatch.setenv(gis.ENV_OVERRIDE, NIEUW_WEBMAP_ID)

    def fake_get(url, params=None, timeout=None, headers=None):
        # Alleen de override-webmap wordt bevraagd; landingspagina hoeft niet.
        if url.endswith("/data"):
            assert NIEUW_WEBMAP_ID in url
            return _mock_response(WEBMAP_RESPONSE)
        return _mock_response({"type": "Web Map"})

    with patch("rotterdam_scanner.gis.requests.get", side_effect=fake_get):
        gis.resolve_layer_urls()

    status = gis.kaartbron_status()
    assert status.bron == "env"
    assert status.waarschuwingen == ()


def test_in_nulquotum_gebied_gebruikt_juiste_laag():
    calls = []

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append(url)
        if url.endswith("/data"):
            return _mock_response(WEBMAP_RESPONSE)
        return _mock_response({"features": [{"attributes": {"OBJECTID": 1}}]})

    with patch("rotterdam_scanner.gis.requests.get", side_effect=fake_get):
        assert gis.in_nulquotum_gebied(1.0, 2.0) is True
    assert any("Nulquotum_test" in c for c in calls)
