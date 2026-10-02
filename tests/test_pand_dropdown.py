"""Tests voor de pand-dropdown in de navbar: alle panden moeten zichtbaar
zijn voor iedereen (ook gebruikers met beperkte toegang), zodat het niet
lijkt alsof er maar één pand bestaat - maar een pand kiezen waar je geen
toegang tot hebt geeft nog steeds de "Geen toegang"-pagina."""
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
        {"slug": "baumannlaan", "naam": "Burgemeester Baumannlaan 70b", "google_sheet_id": "fake2",
         "bunq_rekening_iban": "NL00TEST0000000000"},
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
    return app.test_client()


def _login(client, username, password="geheim123"):
    return client.post("/login", data={"username": username, "password": password})


def test_gebruiker_met_beperkte_toegang_ziet_alle_panden_in_dropdown(client):
    _login(client, "justin")
    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "Mahoniestraat 15" in body
    assert "Burgemeester Baumannlaan 70b" in body  # ook zichtbaar, ook al heeft justin hier geen toegang toe


def test_kiezen_van_pand_zonder_toegang_geeft_geen_toegang_pagina(client):
    _login(client, "justin")
    resp = client.get("/pand/baumannlaan/")
    assert resp.status_code == 403
    assert "Geen toegang" in resp.get_data(as_text=True)


def test_beheerder_met_alle_toegang_ziet_ook_alle_panden(client):
    _login(client, "beheerder")
    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "Mahoniestraat 15" in body
    assert "Burgemeester Baumannlaan 70b" in body
