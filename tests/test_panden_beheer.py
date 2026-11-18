"""Integratietests voor de panden-beheerpagina's (/beheer/panden/...)."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner import db
from kamerverhuur_scanner.config import Config
from webapp.app import create_app


class _FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return []


def _panden(config):
    """De panden zoals ze in de hoofddatabase staan (ruwe opgeslagen dicts),
    vervangt het oude teruglezen van properties.json."""
    return db.laad_panden_ruw(config)


@pytest.fixture
def client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", _FakeSheetClient)

    properties_file = tmp_path / "properties.json"
    properties_file.write_text("[]")
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "beheerder": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
        "justin": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": False, "panden": ["mahoniestraat"]},
    }))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = Config(
        google_service_account_file="fake.json", properties_file=str(properties_file),
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file=str(users_file), flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, state_dir=str(state_dir),
    )
    # Het startpand staat in de hoofddatabase (niet meer in properties.json).
    db.zet_pand(config, "mahoniestraat", {
        "naam": "Mahoniestraat 15", "google_sheet_id": "fake", "bunq_rekening_iban": "NL81BUNQ2163127125",
    })
    app = create_app(config)
    app.testing = True
    return app.test_client(), config


def _login(client, username, password="geheim123"):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


def test_niet_beheerder_kan_niet_bij_panden_beheer(client):
    c, _ = client
    _login(c, "justin")
    resp = c.get("/beheer/panden", follow_redirects=True)
    assert b"Je hebt geen toegang tot gebruikersbeheer" in resp.data


def test_beheerder_ziet_panden_overzicht(client):
    c, _ = client
    _login(c, "beheerder")
    resp = c.get("/beheer/panden")
    assert resp.status_code == 200
    assert b"Mahoniestraat 15" in resp.data


def test_beheerder_kan_nieuw_pand_toevoegen(client):
    c, config = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/nieuw", data={
        "slug": "baumannlaan",
        "naam": "Burgemeester Baumannlaan 70b",
        "google_sheet_id": "sheet-id-123",
        "google_sheet_worksheet": "Huurders",
        "history_worksheet": "Historie",
        "aanmeldingen_worksheet": "Aanmeldingen",
        "bunq_rekening_iban": "nl00 test 0000000000",
    }, follow_redirects=True)
    assert resp.status_code == 200
    panden = _panden(config)
    assert any(p["slug"] == "baumannlaan" for p in panden)
    nieuw = next(p for p in panden if p["slug"] == "baumannlaan")
    assert nieuw["bunq_rekening_iban"] == "NL00TEST0000000000"


def test_ongeldige_slug_wordt_geweigerd(client):
    c, config = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/nieuw", data={
        "slug": "Baumannlaan Fout!", "naam": "X", "google_sheet_id": "y", "bunq_rekening_iban": "NL00TEST0000000000",
    })
    assert b"Slug mag alleen" in resp.data
    panden = _panden(config)
    assert len(panden) == 1


def test_dubbele_slug_wordt_geweigerd(client):
    c, _ = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/nieuw", data={
        "slug": "mahoniestraat", "naam": "X", "google_sheet_id": "y", "bunq_rekening_iban": "NL00TEST0000000000",
    })
    assert b"bestaat al" in resp.data


def test_beheerder_kan_pand_bewerken(client):
    c, config = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/mahoniestraat/bewerken", data={
        "naam": "Mahoniestraat 15 - bijgewerkt",
        "google_sheet_id": "fake",
        "google_sheet_worksheet": "Huurders",
        "history_worksheet": "Historie",
        "aanmeldingen_worksheet": "Aanmeldingen",
        "bunq_rekening_iban": "NL81BUNQ2163127125",
    }, follow_redirects=True)
    assert resp.status_code == 200
    panden = _panden(config)
    assert panden[0]["naam"] == "Mahoniestraat 15 - bijgewerkt"


def test_beheerder_kan_contractgegevens_van_pand_opslaan(client):
    c, config = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/mahoniestraat/bewerken", data={
        "naam": "Mahoniestraat 15",
        "google_sheet_id": "fake",
        "bunq_rekening_iban": "NL81BUNQ2163127125",
        "postcode": "3077WD",
        "plaats": "Rotterdam",
        "verhuurders": "Jurian Reckman | Batavierenplantsoen 33, Haarlem\nJustin Winkelman | Rijksstraatweg 98, Haarlem",
        "rekeninghouder_naam": "JMM Reckman",
        "gedeelde_ruimtes": "keuken, badkamer, tuin",
        "bijzondere_bepalingen": "Geen huisdieren.",
        "gemeente_meldpunt": "www.rotterdam.nl/ongewenst-verhuurgedrag-melden",
    }, follow_redirects=True)
    assert resp.status_code == 200
    panden = _panden(config)
    pand = panden[0]
    assert pand["postcode"] == "3077WD"
    assert pand["plaats"] == "Rotterdam"
    assert pand["verhuurders"] == [
        {"naam": "Jurian Reckman", "adres": "Batavierenplantsoen 33, Haarlem"},
        {"naam": "Justin Winkelman", "adres": "Rijksstraatweg 98, Haarlem"},
    ]
    assert pand["rekeninghouder_naam"] == "JMM Reckman"
    assert pand["gedeelde_ruimtes"] == "keuken, badkamer, tuin"
    assert pand["bijzondere_bepalingen"] == "Geen huisdieren."
    assert pand["gemeente_meldpunt"] == "www.rotterdam.nl/ongewenst-verhuurgedrag-melden"


def test_beheerder_kan_sleutels_opslaan(client):
    c, config = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/mahoniestraat/bewerken", data={
        "naam": "Mahoniestraat 15", "google_sheet_id": "fake", "bunq_rekening_iban": "NL81BUNQ2163127125",
        "sleutels": "Lips 961 zolder straatkant\nLips 961 zolder tuinkant\n\nNemef 1240 BG straatkant",
    }, follow_redirects=True)
    assert resp.status_code == 200
    panden = _panden(config)
    assert panden[0]["sleutels"] == [
        "Lips 961 zolder straatkant", "Lips 961 zolder tuinkant", "Nemef 1240 BG straatkant",
    ]


def test_sleuteloverzicht_toont_sleutels_van_pand(client):
    c, config = client
    _login(c, "beheerder")
    c.post("/beheer/panden/mahoniestraat/bewerken", data={
        "naam": "Mahoniestraat 15", "google_sheet_id": "fake", "bunq_rekening_iban": "NL81BUNQ2163127125",
        "sleutels": "Lips 961 zolder straatkant\nNemef 1240 BG straatkant",
    })
    resp = c.get("/pand/mahoniestraat/sleutels")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Lips 961 zolder straatkant" in body
    assert "Nemef 1240 BG straatkant" in body


def test_sleuteloverzicht_zonder_sleutels_toont_lege_melding(client):
    c, _config = client
    _login(c, "beheerder")
    resp = c.get("/pand/mahoniestraat/sleutels")
    assert resp.status_code == 200
    assert "nog geen sleutels" in resp.get_data(as_text=True).lower()


def test_nieuw_pand_toont_bold_slot_vinkje_standaard_aangevinkt(client):
    c, _config = client
    _login(c, "beheerder")
    resp = c.get("/beheer/panden/nieuw")
    assert resp.status_code == 200
    assert 'name="heeft_bold_slot" checked' in resp.get_data(as_text=True)


def test_beheerder_kan_bold_slot_vinkje_uitzetten(client):
    c, config = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/mahoniestraat/bewerken", data={
        "naam": "Mahoniestraat 15", "google_sheet_id": "fake", "bunq_rekening_iban": "NL81BUNQ2163127125",
        # heeft_bold_slot NIET meegestuurd - simuleert een uitgevinkte checkbox
    }, follow_redirects=True)
    assert resp.status_code == 200
    pand = _panden(config)[0]
    assert pand["heeft_bold_slot"] is False

    bewerk_resp = c.get("/beheer/panden/mahoniestraat/bewerken")
    assert 'name="heeft_bold_slot" checked' not in bewerk_resp.get_data(as_text=True)


def test_beheerder_kan_bold_slot_vinkje_weer_aanzetten(client):
    c, config = client
    _login(c, "beheerder")
    c.post("/beheer/panden/mahoniestraat/bewerken", data={
        "naam": "Mahoniestraat 15", "google_sheet_id": "fake", "bunq_rekening_iban": "NL81BUNQ2163127125",
        "heeft_bold_slot": "on",
    })
    pand = _panden(config)[0]
    assert pand["heeft_bold_slot"] is True


def test_verhuurders_met_komma_i_p_v_pipe_wordt_ook_correct_gesplitst(client):
    # Regressietest voor een echt gemelde situatie: een huurder typt de naam
    # en het adres met een komma i.p.v. het "Naam | Adres"-formaat.
    c, config = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/mahoniestraat/bewerken", data={
        "naam": "Mahoniestraat 15",
        "google_sheet_id": "fake",
        "bunq_rekening_iban": "NL81BUNQ2163127125",
        "verhuurders": (
            "Jurian Reckman, Batavierenplantsoen 33 2025CJ Haarlem\n"
            "Justin Winkelman, Rijksstraatweg 98, 2022 DD Haarlem"
        ),
    }, follow_redirects=True)
    assert resp.status_code == 200
    panden = _panden(config)
    assert panden[0]["verhuurders"] == [
        {"naam": "Jurian Reckman", "adres": "Batavierenplantsoen 33 2025CJ Haarlem"},
        {"naam": "Justin Winkelman", "adres": "Rijksstraatweg 98, 2022 DD Haarlem"},
    ]


def test_beheerder_kan_pand_verwijderen(client):
    c, config = client
    _login(c, "beheerder")
    c.post("/beheer/panden/nieuw", data={
        "slug": "baumannlaan", "naam": "Baumannlaan 70b", "google_sheet_id": "y",
        "bunq_rekening_iban": "NL00TEST0000000000",
    })
    resp = c.post("/beheer/panden/mahoniestraat/verwijderen", follow_redirects=True)
    assert resp.status_code == 200
    panden = _panden(config)
    assert [p["slug"] for p in panden] == ["baumannlaan"]


def test_laatste_pand_kan_niet_verwijderd_worden(client):
    c, config = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/mahoniestraat/verwijderen", follow_redirects=True)
    assert b"laatste overgebleven pand niet verwijderen" in resp.data
    panden = _panden(config)
    assert len(panden) == 1


def test_beheerder_kan_pandkleur_opslaan_en_wissen(client):
    c, config = client
    _login(c, "beheerder")
    # Kleur aanzetten + hex meegeven -> opgeslagen.
    c.post("/beheer/panden/mahoniestraat/bewerken", data={
        "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
        "google_sheet_worksheet": "Huurders", "history_worksheet": "Historie",
        "aanmeldingen_worksheet": "Aanmeldingen", "bunq_rekening_iban": "NL81BUNQ2163127125",
        "kleur_aan": "on", "kleur": "#7b1fa2",
    }, follow_redirects=True)
    assert _panden(config)[0]["kleur"] == "#7b1fa2"

    # Vinkje uit -> kleur gewist (ook al staat er nog een hex in het veld).
    c.post("/beheer/panden/mahoniestraat/bewerken", data={
        "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
        "google_sheet_worksheet": "Huurders", "history_worksheet": "Historie",
        "aanmeldingen_worksheet": "Aanmeldingen", "bunq_rekening_iban": "NL81BUNQ2163127125",
        "kleur": "#7b1fa2",
    }, follow_redirects=True)
    assert _panden(config)[0]["kleur"] == ""
