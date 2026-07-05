from unittest.mock import MagicMock, patch

from rotterdam_scanner.bag import fetch_bag_gegevens


def _mock_response(payload):
    mock = MagicMock()
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


def test_fetch_bag_gegevens_geeft_oppervlakte_en_bouwjaar_terug():
    payload = {"features": [{"properties": {"oppervlakte": 92, "bouwjaar": 1930}}]}
    with patch("rotterdam_scanner.bag.requests.get", return_value=_mock_response(payload)):
        gegevens = fetch_bag_gegevens("0599010000238777")
    assert gegevens.oppervlakte == 92
    assert gegevens.bouwjaar == 1930


def test_fetch_bag_gegevens_geeft_none_zonder_features():
    with patch("rotterdam_scanner.bag.requests.get", return_value=_mock_response({"features": []})):
        assert fetch_bag_gegevens("0599010000238777") is None


def test_fetch_bag_gegevens_geeft_none_bij_leeg_id_zonder_netwerkcall():
    with patch("rotterdam_scanner.bag.requests.get") as mock_get:
        assert fetch_bag_gegevens("") is None
    mock_get.assert_not_called()
