"""Tests voor 'Huuropzegging doorgeven': een nieuwe contract-einddatum voor
een kamer direct vanaf het dashboard verwerken in de sheet."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Tenant
from webapp.app import create_app

KAMER_1 = Tenant(
    row_index=2, naam="Luisa", kamer="1", verwacht_bedrag=Decimal("650.00"),
    email="luisa@example.com", opmerking="rustige huurder",
)
KAMER_2 = Tenant(row_index=3, naam="Vladislav", kamer="2", verwacht_bedrag=Decimal("650.00"))


class FakeSheetClient:
    kamers = [KAMER_1, KAMER_2]
    laatste_update = None

    def __init__(self, _config, _pand):
        pass

    def get_tenants(self):
        return FakeSheetClient.kamers

    def get_kamers(self):
        return FakeSheetClient.kamers

    def update_kamer(self, **kwargs):
        FakeSheetClient.laatste_update = kwargs


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    FakeSheetClient.kamers = [KAMER_1, KAMER_2]
    FakeSheetClient.laatste_update = None

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "bunq_rekening_iban": "NL81BUNQ2163127125"},
    ]))
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "beheerder": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
    }))
    config = Config(
        google_service_account_file="fake.json", properties_file=str(properties_file),
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file=str(users_file), flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14,
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client


def test_formulier_toont_huidige_huurders(app_client):
    resp = app_client.get("/pand/mahoniestraat/huuropzegging")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Luisa" in body
    assert "Vladislav" in body


def test_opzegging_verwerkt_nieuwe_einddatum(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/huuropzegging",
        data={"kamer": "1", "einddatum": "2026-09-30"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    update = FakeSheetClient.laatste_update
    assert update["row_index"] == 2
    assert update["contract_einddatum"] == "30-09-2026"
    # de rest van de kamergegevens mag niet verloren gaan
    assert update["naam"] == "Luisa"
    assert update["email"] == "luisa@example.com"
    assert update["opmerking"] == "rustige huurder"
    assert "verwerkt" in resp.get_data(as_text=True).lower()


def test_opzegging_zonder_kamer_wordt_geweigerd(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/huuropzegging",
        data={"kamer": "", "einddatum": "2026-09-30"},
    )
    assert resp.status_code == 200
    assert FakeSheetClient.laatste_update is None
    assert "kies een huurder" in resp.get_data(as_text=True).lower()


def test_opzegging_zonder_einddatum_wordt_geweigerd(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/huuropzegging",
        data={"kamer": "1", "einddatum": ""},
    )
    assert resp.status_code == 200
    assert "kies een huurder" in resp.get_data(as_text=True).lower()
