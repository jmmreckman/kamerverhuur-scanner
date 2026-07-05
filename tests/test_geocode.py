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


def test_geocode_by_postcode_zonder_treffers_geeft_geocode_error():
    with patch("rotterdam_scanner.geocode.requests.get", return_value=_mock_response([])):
        with pytest.raises(GeocodeError):
            geocode_by_postcode("9999ZZ", "1", "")
