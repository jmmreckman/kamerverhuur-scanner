from unittest.mock import MagicMock, patch

import pytest

from rotterdam_scanner.geocode import GeocodeError, geocode_by_postcode

_DOC = {
    "weergavenaam": "Hillevliet 47A, 3073KJ Rotterdam",
    "straatnaam": "Hillevliet",
    "huis_nlt": "47A",
    "postcode": "3073KJ",
    "woonplaatsnaam": "Rotterdam",
    "buurtnaam": "Bloemhof",
    "wijknaam": "Feijenoord",
    "centroide_rd": "POINT(94177.85 434587.64)",
    "centroide_ll": "POINT(4.4901 51.8901)",
    "nummeraanduiding_id": "0599200000302318",
    "adresseerbaarobject_id": "0599010000027099",
}


def _mock_response(docs):
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"response": {"docs": docs}}
    return mock


def test_geocode_by_postcode_zet_koppelteken_tussen_huisnummer_en_toevoeging():
    with patch("rotterdam_scanner.geocode.requests.get", return_value=_mock_response([_DOC])) as mock_get:
        geocode_by_postcode("3073KJ", "47", "A")
    query = mock_get.call_args.kwargs["params"]["q"]
    assert query == "3073KJ 47-A"


def test_geocode_by_postcode_zonder_toevoeging_geen_los_koppelteken():
    with patch("rotterdam_scanner.geocode.requests.get", return_value=_mock_response([_DOC])) as mock_get:
        geocode_by_postcode("3073KJ", "47", "")
    query = mock_get.call_args.kwargs["params"]["q"]
    assert query == "3073KJ 47"


def test_geocode_by_postcode_geeft_resultaat_terug():
    with patch("rotterdam_scanner.geocode.requests.get", return_value=_mock_response([_DOC])):
        result = geocode_by_postcode("3073KJ", "47", "A")
    assert result.rotterdam_wijk == "Bloemhof"
    assert result.rd_x == 94177.85
    assert result.nummeraanduiding_id == "0599200000302318"


def test_geocode_by_postcode_geeft_lon_lat_terug_voor_de_kaart():
    with patch("rotterdam_scanner.geocode.requests.get", return_value=_mock_response([_DOC])):
        result = geocode_by_postcode("3073KJ", "47", "A")
    assert result.lon == 4.4901
    assert result.lat == 51.8901


def test_geocode_by_postcode_zonder_centroide_ll_geeft_none_voor_lon_lat():
    doc_zonder_ll = {k: v for k, v in _DOC.items() if k != "centroide_ll"}
    with patch("rotterdam_scanner.geocode.requests.get", return_value=_mock_response([doc_zonder_ll])):
        result = geocode_by_postcode("3073KJ", "47", "A")
    assert result.lon is None
    assert result.lat is None


def test_geocode_by_postcode_zonder_treffers_geeft_geocode_error():
    with patch("rotterdam_scanner.geocode.requests.get", return_value=_mock_response([])):
        with pytest.raises(GeocodeError):
            geocode_by_postcode("9999ZZ", "1", "")
