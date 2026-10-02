"""Test dat de kamerpagina de lopende kalendermaand in de betaalgeschiedenis
laat zien, ook als de Historie-sheet die maand nog niet heeft bijgewerkt (bv.
omdat de laatste controle nog niet is geweest) - gebaseerd op de laatste
'Nu controleren'-cache."""
import json
from datetime import date
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner import state
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import HistorieRegel, Status, Tenant, TenantResult
from webapp.app import create_app

KAMER = Tenant(row_index=2, naam="Henri", kamer="1", verwacht_bedrag=Decimal("650.00"))


class FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return [KAMER]

    def get_geschiedenis(self, _kamer):
        return [
            HistorieRegel(
                maand="2026-06", kamer="1", huurder="Henri", verwacht_bedrag=Decimal("650.00"),
                ontvangen_bedrag=Decimal("0"), status=Status.NIET_ONTVANGEN,
            )
        ]


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "bunq_rekening_iban": "NL81BUNQ2163127125"},
    ]))
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "beheerder": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
    }))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = Config(
        google_service_account_file="fake.json", properties_file=str(properties_file),
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file=str(users_file), flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, state_dir=str(state_dir),
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client, config


def test_lopende_maand_verschijnt_ook_zonder_historie_regel(app_client):
    client, config = app_client
    resultaat = TenantResult(tenant=KAMER, ontvangen_bedrag=Decimal("0"), status=Status.NIET_ONTVANGEN)
    state.save("mahoniestraat", [resultaat], 0, state_dir=config.state_dir)

    resp = client.get("/pand/mahoniestraat/kamers/1")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "juni 2026" in body.lower()
    assert f"{_huidige_maandnaam()} {date.today().year}" in body.lower()


def _huidige_maandnaam():
    maanden = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
               "september", "oktober", "november", "december"]
    return maanden[date.today().month - 1]


def test_zonder_cache_blijft_alleen_bestaande_geschiedenis_zichtbaar(app_client):
    client, _config = app_client
    resp = client.get("/pand/mahoniestraat/kamers/1")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "juni 2026" in body.lower() or "2026-06" in body
