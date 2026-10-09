"""Tests voor rotterdam_scanner/bag.py: oppervlakte + gebruiksdoel uit de PDOK BAG-WFS."""
from unittest.mock import MagicMock, patch

from rotterdam_scanner import bag


def _resp(props):
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"features": [{"properties": props}]} if props is not None else {"features": []}
    return mock


def test_gebruiksdoel_tekst_normaliseert_lijst_en_string():
    assert bag._gebruiksdoel_tekst("woonfunctie") == "woonfunctie"
    assert bag._gebruiksdoel_tekst(["woonfunctie", "kantoorfunctie"]) == "woonfunctie, kantoorfunctie"
    assert bag._gebruiksdoel_tekst(None) is None


def test_fetch_geeft_oppervlakte_en_gebruiksdoel():
    props = {"oppervlakte": 254, "bouwjaar": 1911, "gebruiksdoel": "woonfunctie"}
    with patch("rotterdam_scanner.bag.requests.get", return_value=_resp(props)):
        g = bag.fetch_bag_gegevens("0599010000220067")
    assert g.oppervlakte == 254
    assert g.bouwjaar == 1911
    assert g.gebruiksdoel == "woonfunctie"


def test_fetch_zonder_feature_geeft_none():
    with patch("rotterdam_scanner.bag.requests.get", return_value=_resp(None)):
        assert bag.fetch_bag_gegevens("0599010000000000") is None


def test_fetch_leeg_id_geeft_none_zonder_netwerkcall():
    with patch("rotterdam_scanner.bag.requests.get") as mock_get:
        assert bag.fetch_bag_gegevens("") is None
    mock_get.assert_not_called()
