from unittest.mock import MagicMock, patch

import pytest

from rotterdam_scanner import gis


@pytest.fixture(autouse=True)
def _clear_layer_cache():
    gis.resolve_layer_urls.cache_clear()
    yield
    gis.resolve_layer_urls.cache_clear()


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


def test_in_nulquotum_gebied_gebruikt_juiste_laag():
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/data"):
            return _mock_response(WEBMAP_RESPONSE)
        return _mock_response({"features": [{"attributes": {"OBJECTID": 1}}]})

    with patch("rotterdam_scanner.gis.requests.get", side_effect=fake_get):
        assert gis.in_nulquotum_gebied(1.0, 2.0) is True
    assert any("Nulquotum_test" in c for c in calls)
