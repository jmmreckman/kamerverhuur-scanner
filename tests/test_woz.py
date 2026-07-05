from unittest.mock import MagicMock, patch

import pytest

from rotterdam_scanner.woz import WozApiError, fetch_woz_waarden, meest_recente_woz_waarde


def _mock_response(status_code, payload):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


def test_fetch_woz_waarden_sorteert_op_meest_recent_eerst():
    payload = {
        "woz": [
            {"peildatum": "2022-01-01", "vastgesteldeWaarde": 400000},
            {"peildatum": "2024-01-01", "vastgesteldeWaarde": 450000},
            {"peildatum": "2023-01-01", "vastgesteldeWaarde": 420000},
        ]
    }
    with patch("rotterdam_scanner.woz.requests.get", return_value=_mock_response(200, payload)):
        waarden = fetch_woz_waarden("123", "key")

    assert [w.peildatum for w in waarden] == ["2024-01-01", "2023-01-01", "2022-01-01"]
    assert waarden[0].bedrag == 450000


def test_fetch_woz_waarden_lege_lijst_zonder_data():
    with patch("rotterdam_scanner.woz.requests.get", return_value=_mock_response(200, {"woz": []})):
        assert fetch_woz_waarden("123", "key") == []


def test_ongeldige_api_key_geeft_duidelijke_fout():
    with patch("rotterdam_scanner.woz.requests.get", return_value=_mock_response(401, {})):
        with pytest.raises(WozApiError):
            fetch_woz_waarden("123", "verkeerde-key")


def test_meest_recente_woz_waarde_geeft_none_zonder_data():
    with patch("rotterdam_scanner.woz.requests.get", return_value=_mock_response(200, {"woz": []})):
        assert meest_recente_woz_waarde("123", "key") is None


def test_meest_recente_woz_waarde_geeft_hoogste_peildatum():
    payload = {"woz": [{"peildatum": "2023-01-01", "vastgesteldeWaarde": 100}, {"peildatum": "2024-01-01", "vastgesteldeWaarde": 200}]}
    with patch("rotterdam_scanner.woz.requests.get", return_value=_mock_response(200, payload)):
        resultaat = meest_recente_woz_waarde("123", "key")
    assert resultaat.bedrag == 200
    assert resultaat.peildatum == "2024-01-01"
