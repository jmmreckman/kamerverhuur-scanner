from unittest.mock import MagicMock, patch

from rotterdam_scanner.monumenten import (
    _check_beschermd_stadsgezicht,
    _check_mogelijk_gemeentelijk_monument,
    _check_rijksmonument,
    bepaal_huurprijsopslag_signalen,
)


def _mock_response(payload):
    mock = MagicMock()
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


def _lege_response():
    return _mock_response({"features": []})


def test_check_rijksmonument_true_met_url():
    payload = {"features": [{"properties": {"rijksmonumenturl": "https://monumentenregister.cultureelerfgoed.nl/monumenten/1"}}]}
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_mock_response(payload)):
        gevonden, url = _check_rijksmonument(1.0, 2.0)
    assert gevonden is True
    assert url == "https://monumentenregister.cultureelerfgoed.nl/monumenten/1"


def test_check_rijksmonument_false_zonder_features():
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_lege_response()):
        gevonden, url = _check_rijksmonument(1.0, 2.0)
    assert gevonden is False
    assert url is None


def test_check_beschermd_stadsgezicht_true_met_naam():
    payload = {"features": [{"properties": {"NAAM": "Rotterdam - Delfshaven"}}]}
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_mock_response(payload)):
        gevonden, naam = _check_beschermd_stadsgezicht(1.0, 2.0)
    assert gevonden is True
    assert naam == "Rotterdam - Delfshaven"


def test_check_beschermd_stadsgezicht_false_zonder_features():
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_lege_response()):
        gevonden, naam = _check_beschermd_stadsgezicht(1.0, 2.0)
    assert gevonden is False
    assert naam is None


def test_check_mogelijk_gemeentelijk_monument_true_met_omschrijving():
    payload = {"features": [{"attributes": {"USER_Omschrijving": " Voormalig pakhuis, 1910"}}]}
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_mock_response(payload)):
        gevonden, omschrijving = _check_mogelijk_gemeentelijk_monument(1.0, 2.0)
    assert gevonden is True
    assert omschrijving == " Voormalig pakhuis, 1910"


def test_check_mogelijk_gemeentelijk_monument_false_zonder_features():
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_lege_response()):
        gevonden, omschrijving = _check_mogelijk_gemeentelijk_monument(1.0, 2.0)
    assert gevonden is False
    assert omschrijving is None


def test_bepaal_huurprijsopslag_signalen_niets_gevonden_geeft_lege_lijst():
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_lege_response()):
        signalen = bepaal_huurprijsopslag_signalen(1.0, 2.0, bouwjaar=1980)
    assert signalen == []


def test_bepaal_huurprijsopslag_signalen_rijksmonument():
    responses = [
        _mock_response({"features": [{"properties": {"rijksmonumenturl": "https://example.com/1"}}]}),
        _lege_response(),
        _lege_response(),
    ]
    with patch("rotterdam_scanner.monumenten.requests.get", side_effect=responses):
        signalen = bepaal_huurprijsopslag_signalen(1.0, 2.0, bouwjaar=1900)
    assert len(signalen) == 1
    assert "35%" in signalen[0]
    assert "https://example.com/1" in signalen[0]


def test_bepaal_huurprijsopslag_signalen_beschermd_stadsgezicht_toont_bouwjaar():
    responses = [
        _lege_response(),
        _mock_response({"features": [{"properties": {"NAAM": "Rotterdam - Delfshaven"}}]}),
        _lege_response(),
    ]
    with patch("rotterdam_scanner.monumenten.requests.get", side_effect=responses):
        signalen = bepaal_huurprijsopslag_signalen(1.0, 2.0, bouwjaar=1918)
    assert len(signalen) == 1
    assert "5%" in signalen[0]
    assert "Delfshaven" in signalen[0]
    assert "1918" in signalen[0]


def test_bepaal_huurprijsopslag_signalen_nieuwbouw_boven_2024():
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_lege_response()):
        signalen = bepaal_huurprijsopslag_signalen(1.0, 2.0, bouwjaar=2025)
    assert len(signalen) == 1
    assert "10%" in signalen[0]
    assert "2025" in signalen[0]


def test_bepaal_huurprijsopslag_signalen_geen_nieuwbouw_onder_2024():
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_lege_response()):
        signalen = bepaal_huurprijsopslag_signalen(1.0, 2.0, bouwjaar=2010)
    assert signalen == []


def test_bepaal_huurprijsopslag_signalen_zonder_bouwjaar_geen_nieuwbouwsignaal():
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_lege_response()):
        signalen = bepaal_huurprijsopslag_signalen(1.0, 2.0, bouwjaar=None)
    assert signalen == []


def test_bepaal_huurprijsopslag_signalen_mogelijk_gemeentelijk_monument():
    responses = [
        _lege_response(),
        _lege_response(),
        _mock_response({"features": [{"attributes": {"USER_Omschrijving": "Voormalig pakhuis"}}]}),
    ]
    with patch("rotterdam_scanner.monumenten.requests.get", side_effect=responses):
        signalen = bepaal_huurprijsopslag_signalen(1.0, 2.0, bouwjaar=1900)
    assert len(signalen) == 1
    assert "15%" in signalen[0]
    assert "Voormalig pakhuis" in signalen[0]
    assert "monumentenregister.rotterdam.nl" in signalen[0]


def test_bepaal_huurprijsopslag_signalen_combineert_alle_signalen():
    responses = [
        _mock_response({"features": [{"properties": {"rijksmonumenturl": None}}]}),
        _mock_response({"features": [{"properties": {"NAAM": "Test-gezicht"}}]}),
        _mock_response({"features": [{"attributes": {"USER_Omschrijving": None}}]}),
    ]
    with patch("rotterdam_scanner.monumenten.requests.get", side_effect=responses):
        signalen = bepaal_huurprijsopslag_signalen(1.0, 2.0, bouwjaar=2025)
    assert len(signalen) == 4
