"""Tests voor de gratis beschikbaarheid-check - requests.get wordt hier nooit
echt aangeroepen, alleen gemockt. De titel-teksten zijn gebaseerd op echte
Funda-pagina's (juli 2026): "<type> te koop: <adres>" voor actief,
"<type> verkocht: <adres>" zodra verkocht."""
from unittest.mock import MagicMock, patch

import requests

from rotterdam_scanner import beschikbaarheid


def _resp(status_code=200, html=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = html
    return resp


def test_te_koop_titel_geeft_true():
    html = "<html><head><title>Appartement te koop: Halvemaanpassage 15 3011 DL Rotterdam | Funda</title></head></html>"
    with patch("rotterdam_scanner.beschikbaarheid.requests.get", return_value=_resp(html=html)):
        assert beschikbaarheid.controleer_beschikbaar("https://example.com", pauzeer=False) is True


def test_verkocht_titel_geeft_false():
    html = "<html><head><title>Appartement verkocht: Paltroklaan 37 3052 HG Rotterdam | Funda</title></head></html>"
    with patch("rotterdam_scanner.beschikbaarheid.requests.get", return_value=_resp(html=html)):
        assert beschikbaarheid.controleer_beschikbaar("https://example.com", pauzeer=False) is False


def test_geen_titel_geeft_none():
    with patch("rotterdam_scanner.beschikbaarheid.requests.get", return_value=_resp(html="<html></html>")):
        assert beschikbaarheid.controleer_beschikbaar("https://example.com", pauzeer=False) is None


def test_onherkende_titel_geeft_none():
    html = "<html><head><title>Even geduld a.u.b. | Funda</title></head></html>"
    with patch("rotterdam_scanner.beschikbaarheid.requests.get", return_value=_resp(html=html)):
        assert beschikbaarheid.controleer_beschikbaar("https://example.com", pauzeer=False) is None


def test_niet_200_status_geeft_none():
    with patch("rotterdam_scanner.beschikbaarheid.requests.get", return_value=_resp(status_code=404)):
        assert beschikbaarheid.controleer_beschikbaar("https://example.com", pauzeer=False) is None


def test_netwerkfout_geeft_none_zonder_crash():
    with patch(
        "rotterdam_scanner.beschikbaarheid.requests.get",
        side_effect=requests.ConnectionError("boom"),
    ):
        assert beschikbaarheid.controleer_beschikbaar("https://example.com", pauzeer=False) is None


def test_pauzeer_true_roept_time_sleep_aan():
    html = "<title>Huis te koop: Teststraat 1 | Funda</title>"
    with patch("rotterdam_scanner.beschikbaarheid.requests.get", return_value=_resp(html=html)), \
         patch("rotterdam_scanner.beschikbaarheid.time.sleep") as mock_sleep:
        beschikbaarheid.controleer_beschikbaar("https://example.com")
    mock_sleep.assert_called_once()


def test_pauzeer_false_slaat_time_sleep_over():
    html = "<title>Huis te koop: Teststraat 1 | Funda</title>"
    with patch("rotterdam_scanner.beschikbaarheid.requests.get", return_value=_resp(html=html)), \
         patch("rotterdam_scanner.beschikbaarheid.time.sleep") as mock_sleep:
        beschikbaarheid.controleer_beschikbaar("https://example.com", pauzeer=False)
    mock_sleep.assert_not_called()
