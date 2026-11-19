"""Tests voor de 'Wissel van pand'-dropdown in de navigatie: moet zoveel
mogelijk op dezelfde (soort) pagina blijven voor het andere pand, i.p.v.
altijd terug te vallen op het dashboard."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Tenant
from webapp.app import create_app

KAMER_1 = Tenant(row_index=2, naam="Bence Neumayer", kamer="1", verwacht_bedrag=Decimal("919.00"))


class FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return [KAMER_1]

    def get_tenants(self):
        return [KAMER_1]

    def get_geschiedenis(self, _kamer_naam):
        return []

    def get_recent_vertrokken_huurders(self):
        return []


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    monkeypatch.chdir(tmp_path)

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "bunq_rekening_iban": "NL81BUNQ2163127125"},
        {"slug": "baumannlaan", "naam": "Baumannlaan 70b", "google_sheet_id": "fake2",
         "bunq_rekening_iban": "NL00TEST0000000000"},
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


def test_dropdown_op_kamers_overzicht_wisselt_naar_kamers_overzicht_ander_pand(app_client):
    resp = app_client.get("/pand/mahoniestraat/kamers")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '<option value="/pand/baumannlaan/kamers"' in body


def test_dropdown_op_kamer_detail_valt_terug_op_kamers_overzicht(app_client):
    resp = app_client.get("/pand/mahoniestraat/kamers/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # de kamer "1" bestaat mogelijk niet bij het andere pand, dus terug naar
    # de overzichtspagina van diezelfde sectie i.p.v. dezelfde kamer-URL
    assert '<option value="/pand/baumannlaan/kamers"' in body
    assert "/pand/baumannlaan/kamers/1" not in body


def test_dropdown_op_dashboard_wisselt_naar_dashboard_ander_pand(app_client):
    resp = app_client.get("/pand/mahoniestraat/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '<option value="/pand/baumannlaan/"' in body or '<option value="/pand/baumannlaan/dashboard"' in body


def test_dropdown_op_pand_bewerken_wisselt_naar_pand_bewerken_ander_pand(app_client):
    resp = app_client.get("/beheer/panden/mahoniestraat/bewerken")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '<option value="/beheer/panden/baumannlaan/bewerken"' in body


def test_dropdown_op_contracten_wisselt_naar_contracten_ander_pand(app_client):
    resp = app_client.get("/pand/mahoniestraat/contracten")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '<option value="/pand/baumannlaan/contracten"' in body
