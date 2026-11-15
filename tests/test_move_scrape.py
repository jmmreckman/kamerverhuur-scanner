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


def _edge_met_kenmerken(object_type, secties, tekst=""):
    return {
        "node": {
            "exchangeObject": {
                "address": {"street": "Testlaan", "nr": 1, "nrExtension": "", "city": "Rotterdam", "zipCode": "3011 AA"},
                "koopPrice": {"formatMoneyLong": "€ 300.000,- k.k."},
                "woonOppervlakte": 80,
                "aantalKamers": 4,
                "status": "BESCHIKBAAR",
                "objectDetailedType": object_type,
                "aanbiedingsTekst": tekst,
                "kenmerkSections": secties,
            }
        }
    }


def _sectie(naam, **paren):
    return {"name": naam, "kenmerken": [{"label": k, "value": v} for k, v in paren.items()]}


def test_parse_move_kenmerken_appartement_erfpacht_vve():
    edge = _edge_met_kenmerken(
        "PORTIEKFLAT",
        [
            {"name": "Overdracht", "kenmerken": [{"label": "Bijdrage VVE p/m", "value": "€ 301,26"}]},
            {"name": "VvE checklist", "kenmerken": [{"label": "Periodieke bijdrage", "value": "Ja (€ 301,26 p.m.)"}]},
            {"name": "Kadastrale gegevens", "kenmerken": [{"label": "Eigendomssituatie", "value": "Erfpacht"}]},
        ],
    )
    w = move_scrape.parse_move_woningen([edge])[0]
    assert w.eigendom_soort == "erfpacht"
    assert w.heeft_vve is True
    assert w.vve_bijdrage_pm == 301.26
    assert w.zelfbewoningsplicht is False


def test_parse_move_kenmerken_woonhuis_eigen_grond_geen_vve():
    edge = _edge_met_kenmerken(
        "TUSSENWONING",
        [{"name": "Kadastrale gegevens", "kenmerken": [{"label": "Eigendomssituatie", "value": "Volle eigendom"}]}],
    )
    w = move_scrape.parse_move_woningen([edge])[0]
    assert w.eigendom_soort == "eigen_grond"
    assert w.heeft_vve is False
    assert w.vve_bijdrage_pm is None


def test_parse_move_kenmerken_zelfbewoningsplicht_uit_tekst():
    edge = _edge_met_kenmerken(
        "TUSSENWONING",
        [],
        tekst="Voor deze woning geldt een zelfbewoningsplicht van vier jaar.",
    )
    w = move_scrape.parse_move_woningen([edge])[0]
    assert w.zelfbewoningsplicht is True


def test_parse_move_kenmerken_niet_clausule_en_afgekocht():
    edge = _edge_met_kenmerken(
        "HERENHUIS",
        [{"name": "Kadastrale gegevens", "kenmerken": [{"label": "Eigendomssituatie", "value": "Erfpacht"}]}],
        tekst="De erfpacht is eeuwigdurend afgekocht. Een niet-zelfbewoningsclausule is van toepassing.",
    )
    w = move_scrape.parse_move_woningen([edge])[0]
    assert w.eigendom_soort == "erfpacht_afgekocht"
    assert w.niet_zelfbewoningsclausule is True
    assert w.zelfbewoningsplicht is False


def test_parse_move_zonder_kenmerken_crasht_niet():
    # Een Move-edge zonder kenmerkSections mag niet crashen; zonder Eigendomssituatie-
    # kenmerk en zonder tekst is het eigendom "onbekend" (Move-gezien maar onbekend,
    # niet None - None is voorbehouden aan Funda-only/legacy), en geen zelfbewoningsplicht.
    edges = [_edge("Leegstraat", 9, "", "Rotterdam", "3011 ZZ", "€ 250.000,- k.k.", 55, "BESCHIKBAAR")]
    w = move_scrape.parse_move_woningen(edges)[0]
    assert w.eigendom_soort == "onbekend"
    assert w.zelfbewoningsplicht is False


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
