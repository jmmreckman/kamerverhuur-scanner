"""Integratietests voor de panden-beheerpagina's (/beheer/panden/...)."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from webapp.app import create_app


class _FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return []


@pytest.fixture
def client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", _FakeSheetClient)

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "bunq_rekening_iban": "NL81BUNQ2163127125"},
    ]))
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "beheerder": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
        "justin": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": False, "panden": ["mahoniestraat"]},
    }))
    config = Config(
        google_service_account_file="fake.json", properties_file=str(properties_file),
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file=str(users_file), flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14,
    )
    app = create_app(config)
    app.testing = True
    return app.test_client(), properties_file


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
    c, properties_file = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/nieuw", data={
        "slug": "baumannlaan",
        "naam": "Burgemeester Baumannlaan 70b",
        "google_sheet_id": "sheet-id-123",
        "google_sheet_worksheet": "Huurders",
        "history_worksheet": "Historie",
        "aanmeldingen_worksheet": "Aanmeldingen",
        "google_drive_folder_id": "",
        "bunq_rekening_iban": "nl00 test 0000000000",
    }, follow_redirects=True)
    assert resp.status_code == 200
    panden = json.loads(properties_file.read_text())
    assert any(p["slug"] == "baumannlaan" for p in panden)
    nieuw = next(p for p in panden if p["slug"] == "baumannlaan")
    assert nieuw["bunq_rekening_iban"] == "NL00TEST0000000000"


def test_ongeldige_slug_wordt_geweigerd(client):
    c, properties_file = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/nieuw", data={
        "slug": "Baumannlaan Fout!", "naam": "X", "google_sheet_id": "y", "bunq_rekening_iban": "NL00TEST0000000000",
    })
    assert b"Slug mag alleen" in resp.data
    panden = json.loads(properties_file.read_text())
    assert len(panden) == 1


def test_dubbele_slug_wordt_geweigerd(client):
    c, _ = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/nieuw", data={
        "slug": "mahoniestraat", "naam": "X", "google_sheet_id": "y", "bunq_rekening_iban": "NL00TEST0000000000",
    })
    assert b"bestaat al" in resp.data


def test_beheerder_kan_pand_bewerken(client):
    c, properties_file = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/mahoniestraat/bewerken", data={
        "naam": "Mahoniestraat 15 - bijgewerkt",
        "google_sheet_id": "fake",
        "google_sheet_worksheet": "Huurders",
        "history_worksheet": "Historie",
        "aanmeldingen_worksheet": "Aanmeldingen",
        "google_drive_folder_id": "",
        "bunq_rekening_iban": "NL81BUNQ2163127125",
    }, follow_redirects=True)
    assert resp.status_code == 200
    panden = json.loads(properties_file.read_text())
    assert panden[0]["naam"] == "Mahoniestraat 15 - bijgewerkt"


def test_beheerder_kan_pand_verwijderen(client):
    c, properties_file = client
    _login(c, "beheerder")
    c.post("/beheer/panden/nieuw", data={
        "slug": "baumannlaan", "naam": "Baumannlaan 70b", "google_sheet_id": "y",
        "bunq_rekening_iban": "NL00TEST0000000000",
    })
    resp = c.post("/beheer/panden/mahoniestraat/verwijderen", follow_redirects=True)
    assert resp.status_code == 200
    panden = json.loads(properties_file.read_text())
    assert [p["slug"] for p in panden] == ["baumannlaan"]


def test_laatste_pand_kan_niet_verwijderd_worden(client):
    c, properties_file = client
    _login(c, "beheerder")
    resp = c.post("/beheer/panden/mahoniestraat/verwijderen", follow_redirects=True)
    assert b"laatste overgebleven pand niet verwijderen" in resp.data
    panden = json.loads(properties_file.read_text())
    assert len(panden) == 1
