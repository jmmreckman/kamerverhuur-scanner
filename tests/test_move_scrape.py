from types import SimpleNamespace

from rotterdam_scanner import move_scrape
from rotterdam_scanner.config import _move_dossier_id


def _edge(street, nr, ext, city, zip_, prijs_tekst, opp, status):
    return {
        "node": {
            "exchangeObject": {
                "address": {"street": street, "nr": nr, "nrExtension": ext, "city": city, "zipCode": zip_},
                "koopPrice": {"formatMoneyLong": prijs_tekst} if prijs_tekst else None,
                "woonOppervlakte": opp,
                "aantalKamers": 3,
                "status": status,
                "objectDetailedType": "BENEDENWONING",
            }
        }
    }


def test_parse_move_woningen_mapt_velden():
    edges = [
        _edge("Hillegondastraat", 12, "A", "Rotterdam", "3051 PB", "€ 345.000,- kosten koper", 66, "BESCHIKBAAR")
    ]
    woningen = move_scrape.parse_move_woningen(edges)
    assert len(woningen) == 1
    w = woningen[0]
    assert w.object_id == "3051PB-12A"
    assert w.straatnaam == "Hillegondastraat"
    assert w.huisnummer == "12"
    assert w.toevoeging == "A"
    assert w.postcode == "3051PB"
    assert w.woonplaats == "Rotterdam"
    assert w.prijs == 345000
    assert w.oppervlakte_advertentie == 66
    assert w.bron == "nvm"


def test_parse_move_woningen_zonder_toevoeging():
    edges = [_edge("Harry Pauwlaan", 50, "", "'S-Gravenhage", "2497 AN", "€ 775.000,- k.k.", 185, "BESCHIKBAAR")]
    w = move_scrape.parse_move_woningen(edges)[0]
    assert w.object_id == "2497AN-50"
    assert w.toevoeging == ""
    assert w.prijs == 775000


def test_parse_move_woningen_slaat_verkocht_over():
    edges = [
        _edge("Verkochtstraat", 1, "", "Rotterdam", "3011 AA", "€ 200.000,- k.k.", 50, "VERKOCHT"),
        _edge("Kansstraat", 2, "", "Rotterdam", "3011 AB", "€ 250.000,- k.k.", 60, "BESCHIKBAAR"),
        _edge("Bodstraat", 3, "", "Rotterdam", "3011 AC", "€ 260.000,- k.k.", 61, "ONDER_BOD"),
    ]
    ids = {w.object_id for w in move_scrape.parse_move_woningen(edges)}
    assert "3011AA-1" not in ids  # verkocht -> overgeslagen
    assert "3011AB-2" in ids  # beschikbaar
    assert "3011AC-3" in ids  # onder bod telt nog als kans


def test_parse_move_woningen_zonder_prijs_geeft_none():
    edges = [_edge("Prijsloos", 5, "", "Rotterdam", "3011 AD", None, 70, "BESCHIKBAAR")]
    assert move_scrape.parse_move_woningen(edges)[0].prijs is None


def test_code_uit_locatie():
    loc = "https://move.nl/?state=abc&code=XYZ123&session_state=foo"
    assert move_scrape._code_uit_locatie(loc) == "XYZ123"
    assert move_scrape._code_uit_locatie("https://move.nl/?error=access_denied") is None


def test_haal_move_woningen_zonder_config_slaat_over():
    cfg = SimpleNamespace(move_email="", move_password="", move_dossier_id="")
    woningen, waarschuwingen = move_scrape.haal_move_woningen(cfg)
    assert woningen == []
    assert waarschuwingen == []


def test_move_dossier_id_uit_url():
    url = "https://move.nl/searcher-dossier/U2VhcmNoZXJEb3NzaWVyOjEyMw==/mijn-gevonden-woningen"
    assert _move_dossier_id(url) == "U2VhcmNoZXJEb3NzaWVyOjEyMw=="
    assert _move_dossier_id("U2VhcmNoZXJEb3NzaWVyOjEyMw==") == "U2VhcmNoZXJEb3NzaWVyOjEyMw=="
    assert _move_dossier_id("") == ""
