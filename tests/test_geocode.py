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


_DOC_19A = {**_DOC, "weergavenaam": "Grondherendijk 19A, 3082DD Rotterdam", "huis_nlt": "19A"}
_DOC_19B = {**_DOC, "weergavenaam": "Grondherendijk 19B, 3082DD Rotterdam", "huis_nlt": "19B"}


def _side_effect_meerdere_eenheden(hoofdresultaat, alle_eenheden):
    def _get(url, params, timeout):  # noqa: ANN001 - matcht requests.get-signatuur
        if params["rows"] == 1:
            return _mock_response([hoofdresultaat])
        return _mock_response(alle_eenheden)

    return _get


def test_geocode_by_postcode_zonder_toevoeging_bij_meerdere_eenheden_geeft_geocode_error():
    # Reproduceert de Grondherendijk-19-bug: mail-tekst zonder toevoeging ("19"), terwijl
    # er op dat huisnummer meerdere eenheden bestaan (19A en 19B) -- moet NIET stilzwijgend
    # de eerste eenheid (19A) teruggeven (dat pakte toen de verkeerde advertentie).
    with patch(
        "rotterdam_scanner.geocode.requests.get",
        side_effect=_side_effect_meerdere_eenheden(_DOC_19A, [_DOC_19A, _DOC_19B]),
    ):
        with pytest.raises(GeocodeError, match="meerdere eenheden"):
            geocode_by_postcode("3082DD", "19", "")


def test_geocode_by_postcode_zonder_toevoeging_bij_enkele_eenheid_werkt_gewoon():
    with patch(
        "rotterdam_scanner.geocode.requests.get",
        side_effect=_side_effect_meerdere_eenheden(_DOC, [_DOC]),
    ):
        result = geocode_by_postcode("3073KJ", "47", "")
    assert result.huisnummer == "47A"


def test_geocode_by_postcode_met_toevoeging_checkt_niet_op_meerdere_eenheden():
    # Als er al een toevoeging is meegegeven, is het al ondubbelzinnig -- geen extra
    # PDOK-aanroep nodig (en dus geen risico dat die per ongeluk toch een fout oplevert).
    with patch("rotterdam_scanner.geocode.requests.get", return_value=_mock_response([_DOC])) as mock_get:
        geocode_by_postcode("3073KJ", "47", "A")
    assert mock_get.call_count == 1


def test_geocode_by_postcode_met_letter_in_huisnummer_checkt_niet_op_meerdere_eenheden():
    # ListingState.huisnummer slaat de toevoeging al gecombineerd op (bv. "47A") en wordt
    # zo doorgegeven door de backvul-functies met een lege toevoeging - dat is al
    # ondubbelzinnig (geen kale cijferreeks), dus geen extra check nodig.
    with patch("rotterdam_scanner.geocode.requests.get", return_value=_mock_response([_DOC])) as mock_get:
        geocode_by_postcode("3073KJ", "47A", "")
    assert mock_get.call_count == 1


def test_geocode_by_postcode_probeert_opnieuw_bij_tijdelijke_timeout():
    # Twee keer een read-timeout, dan een geldige response -> moet alsnog slagen
    # (geen onnodig gesneuveld adres bij een tijdelijke PDOK-storing).
    import requests as _requests
    beurten = [
        _requests.exceptions.ReadTimeout("read timed out"),
        _requests.exceptions.ReadTimeout("read timed out"),
        _mock_response([_DOC]),
    ]
    with patch("rotterdam_scanner.geocode.time.sleep"), patch(
        "rotterdam_scanner.geocode.requests.get", side_effect=beurten
    ) as mock_get:
        result = geocode_by_postcode("3073KJ", "47A")
    assert result.postcode == "3073KJ"
    assert mock_get.call_count == 3


def test_geocode_by_postcode_gooit_fout_door_na_alle_pogingen():
    import requests as _requests
    with patch("rotterdam_scanner.geocode.time.sleep"), patch(
        "rotterdam_scanner.geocode.requests.get",
        side_effect=_requests.exceptions.ReadTimeout("read timed out"),
    ) as mock_get:
        with pytest.raises(_requests.exceptions.ReadTimeout):
            geocode_by_postcode("3073KJ", "47A")
    assert mock_get.call_count == 3
