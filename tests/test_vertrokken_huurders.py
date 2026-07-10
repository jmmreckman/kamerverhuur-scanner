"""Tests voor het archiveren van vertrokken huurders: blijven nog even
(grijs, tot 1 maand na hun contract-einddatum) zichtbaar op de
Huurders-pagina zodra een kamer een andere huurder krijgt."""
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Tenant, VertrokkenHuurder
from webapp.app import create_app

KAMER_1 = Tenant(
    row_index=2, naam="Bence Neumayer", kamer="1", verwacht_bedrag=Decimal("919.00"),
    email="bence@example.com", telefoonnummer="0612345678", contract_einddatum="01-07-2026",
)


class FakeSheetClient:
    laatste_update = None
    archiveer_aangeroepen_met = None
    vertrokken_huurders = []

    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return [KAMER_1]

    def get_tenants(self):
        return [KAMER_1]

    def update_kamer(self, **kwargs):
        FakeSheetClient.laatste_update = kwargs

    def archiveer_vertrokken_huurder(self, kamer):
        FakeSheetClient.archiveer_aangeroepen_met = kamer

    def get_recent_vertrokken_huurders(self):
        return FakeSheetClient.vertrokken_huurders


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    FakeSheetClient.laatste_update = None
    FakeSheetClient.archiveer_aangeroepen_met = None
    FakeSheetClient.vertrokken_huurders = []

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
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, state_dir=str(tmp_path),
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client


def test_huurder_bewerken_naar_andere_naam_archiveert_de_vertrekkende(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/huurders/1/bewerken",
        data={"kamer": "1", "naam": "Nieuwe Huurder", "verwacht_bedrag": "919,00"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    gearchiveerd = FakeSheetClient.archiveer_aangeroepen_met
    assert gearchiveerd is not None
    assert gearchiveerd.naam == "Bence Neumayer"


def test_huurder_bewerken_zelfde_naam_archiveert_niet(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/huurders/1/bewerken",
        data={"kamer": "1", "naam": "Bence Neumayer", "verwacht_bedrag": "925,00"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert FakeSheetClient.archiveer_aangeroepen_met is None


def test_huurder_bewerken_kamer_leegmaken_archiveert(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/huurders/1/bewerken",
        data={"kamer": "1", "naam": "", "verwacht_bedrag": "919,00"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    gearchiveerd = FakeSheetClient.archiveer_aangeroepen_met
    assert gearchiveerd is not None
    assert gearchiveerd.naam == "Bence Neumayer"


def test_huurders_pagina_toont_vertrokken_huurder_grijs_gemarkeerd(app_client):
    FakeSheetClient.vertrokken_huurders = [
        VertrokkenHuurder(
            kamer="1", naam="Oud-Huurder", email="oud@example.com", telefoonnummer="0698765432",
            contract_einddatum="01-07-2026", vertrokken_op=date.today() - timedelta(days=3),
        )
    ]
    resp = app_client.get("/pand/mahoniestraat/huurders")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Oud-Huurder" in body
    assert "voormalig" in body.lower()
    assert "oud@example.com" in body


def test_huurders_pagina_zonder_vertrokken_huurders_toont_geen_sectie(app_client):
    resp = app_client.get("/pand/mahoniestraat/huurders")
    assert resp.status_code == 200
    assert "Voormalige huurders" not in resp.get_data(as_text=True)
