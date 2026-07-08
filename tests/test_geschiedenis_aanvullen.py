"""Integratietest voor de 'Betaalgeschiedenis aanvullen'-knop op de
Betalingen-pagina."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from webapp.app import create_app


class FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return []


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)

    aangeroepen = []

    def _fake_backfill(config, pand, aantal_maanden=12):
        aangeroepen.append((pand.slug, aantal_maanden))
        return 12

    monkeypatch.setattr(appmodule, "backfill_geschiedenis", _fake_backfill)

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
    return client, aangeroepen


def test_geschiedenis_aanvullen_roept_backfill_aan_en_flasht(app_client):
    client, aangeroepen = app_client
    resp = client.post("/pand/mahoniestraat/betalingen/geschiedenis-aanvullen", follow_redirects=True)
    assert resp.status_code == 200
    assert aangeroepen == [("mahoniestraat", 12)]
    assert "aangevuld voor de laatste 12 maanden" in resp.get_data(as_text=True)
