from unittest.mock import MagicMock, patch

from rotterdam_scanner.monumenten import (
    _check_beschermd_stadsgezicht,
    _check_mogelijk_gemeentelijk_monument,
    _check_rijksmonument,
    bepaal_huurprijsopslag,
    hoogste_opslagpercentage,
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


def test_bepaal_huurprijsopslag_niets_gevonden_geeft_lege_lijst():
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_lege_response()):
        signalen = bepaal_huurprijsopslag(1.0, 2.0, bouwjaar=1980)
    assert signalen == []


def test_bepaal_huurprijsopslag_rijksmonument():
    responses = [
        _mock_response({"features": [{"properties": {"rijksmonumenturl": "https://example.com/1"}}]}),
        _lege_response(),
        _lege_response(),
    ]
    with patch("rotterdam_scanner.monumenten.requests.get", side_effect=responses):
        signalen = bepaal_huurprijsopslag(1.0, 2.0, bouwjaar=1900)
    assert len(signalen) == 1
    assert signalen[0].percentage == 0.35
    assert "35%" in signalen[0].tekst
    assert "https://example.com/1" in signalen[0].tekst


def test_bepaal_huurprijsopslag_beschermd_stadsgezicht_voor_1965_telt_mee():
    responses = [
        _lege_response(),
        _mock_response({"features": [{"properties": {"NAAM": "Rotterdam - Delfshaven"}}]}),
        _lege_response(),
    ]
    with patch("rotterdam_scanner.monumenten.requests.get", side_effect=responses):
        signalen = bepaal_huurprijsopslag(1.0, 2.0, bouwjaar=1918)
    assert len(signalen) == 1
    assert signalen[0].percentage == 0.05
    assert "Delfshaven" in signalen[0].tekst
    assert "1918" in signalen[0].tekst


def test_bepaal_huurprijsopslag_beschermd_stadsgezicht_na_1965_telt_niet_mee():
    # WWS-regel: de 5%-opslag voor beschermd stadsgezicht geldt alleen voor panden
    # van vóór 1965 - een latente bug die nooit echt gecontroleerd werd (stond alleen
    # in de tekst), nu wél afgedwongen omdat dit financieel meetelt.
    responses = [
        _lege_response(),
        _mock_response({"features": [{"properties": {"NAAM": "Rotterdam - Delfshaven"}}]}),
        _lege_response(),
    ]
    with patch("rotterdam_scanner.monumenten.requests.get", side_effect=responses):
        signalen = bepaal_huurprijsopslag(1.0, 2.0, bouwjaar=1970)
    assert signalen == []


def test_bepaal_huurprijsopslag_beschermd_stadsgezicht_zonder_bouwjaar_telt_niet_mee():
    responses = [
        _lege_response(),
        _mock_response({"features": [{"properties": {"NAAM": "Rotterdam - Delfshaven"}}]}),
        _lege_response(),
    ]
    with patch("rotterdam_scanner.monumenten.requests.get", side_effect=responses):
        signalen = bepaal_huurprijsopslag(1.0, 2.0, bouwjaar=None)
    assert signalen == []


def test_bepaal_huurprijsopslag_nieuwbouw_boven_2024():
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_lege_response()):
        signalen = bepaal_huurprijsopslag(1.0, 2.0, bouwjaar=2025)
    assert len(signalen) == 1
    assert signalen[0].percentage == 0.10
    assert "2025" in signalen[0].tekst


def test_bepaal_huurprijsopslag_geen_nieuwbouw_onder_2024():
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_lege_response()):
        signalen = bepaal_huurprijsopslag(1.0, 2.0, bouwjaar=2010)
    assert signalen == []


def test_bepaal_huurprijsopslag_zonder_bouwjaar_geen_nieuwbouwsignaal():
    with patch("rotterdam_scanner.monumenten.requests.get", return_value=_lege_response()):
        signalen = bepaal_huurprijsopslag(1.0, 2.0, bouwjaar=None)
    assert signalen == []


def test_bepaal_huurprijsopslag_mogelijk_gemeentelijk_monument():
    responses = [
        _lege_response(),
        _lege_response(),
        _mock_response({"features": [{"attributes": {"USER_Omschrijving": "Voormalig pakhuis"}}]}),
    ]
    with patch("rotterdam_scanner.monumenten.requests.get", side_effect=responses):
        signalen = bepaal_huurprijsopslag(1.0, 2.0, bouwjaar=1900)
    assert len(signalen) == 1
    assert signalen[0].percentage == 0.15
    assert "Voormalig pakhuis" in signalen[0].tekst
    assert "monumentenregister.rotterdam.nl" in signalen[0].tekst


def test_bepaal_huurprijsopslag_combineert_alle_signalen():
    responses = [
        _mock_response({"features": [{"properties": {"rijksmonumenturl": None}}]}),
        _mock_response({"features": [{"properties": {"NAAM": "Test-gezicht"}}]}),
        _mock_response({"features": [{"attributes": {"USER_Omschrijving": None}}]}),
    ]
    with patch("rotterdam_scanner.monumenten.requests.get", side_effect=responses):
        signalen = bepaal_huurprijsopslag(1.0, 2.0, bouwjaar=1920)
    # rijksmonument (35%) + stadsgezicht (5%, bouwjaar 1920 < 1965) + gemeentelijk monument (15%)
    # -- nieuwbouwsignaal komt er niet bij aangezien bouwjaar 1920 geen nieuwbouw is.
    assert len(signalen) == 3


def test_hoogste_opslagpercentage_neemt_maximum_niet_de_som():
    from rotterdam_scanner.monumenten import HuurprijsopslagSignaal

    signalen = [
        HuurprijsopslagSignaal(percentage=0.05, tekst="stadsgezicht"),
        HuurprijsopslagSignaal(percentage=0.35, tekst="rijksmonument"),
    ]
    assert hoogste_opslagpercentage(signalen) == 0.35


def test_hoogste_opslagpercentage_leeg_geeft_nul():
    assert hoogste_opslagpercentage([]) == 0.0
