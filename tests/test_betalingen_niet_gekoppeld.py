"""Integratietest: de betalingenpagina moet de details van niet-gekoppelde
inkomende betalingen ook tonen bij een gewoon (GET-)bezoek, niet alleen
meteen na een verse 'Nu controleren'-klik - anders meldt het dashboard wel
"X betaling(en) niet gekoppeld" terwijl de betalingenpagina zelf leeg lijkt."""
import json
from datetime import date
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner import state
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Payment, Status, Tenant, TenantResult
from webapp.app import create_app


class FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return [Tenant(row_index=2, naam="Miruna", kamer="bg-straatkant", verwacht_bedrag=Decimal("650.00"))]


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


def test_niet_gekoppelde_betaling_zichtbaar_bij_gewoon_bezoek(app_client):
    client, config = app_client
    tenant = Tenant(row_index=2, naam="Miruna", kamer="bg-straatkant", verwacht_bedrag=Decimal("650.00"))
    resultaat = TenantResult(tenant=tenant, ontvangen_bedrag=Decimal("0"), status=Status.NIET_ONTVANGEN)
    betaling = Payment(
        bedrag=Decimal("650.00"), valuta="EUR", tegenpartij_naam="M Poncea Andronescu",
        tegenpartij_iban="NL91ABNA0417164300", omschrijving="Huur juli bg-straatkant",
        datum=date(2026, 7, 24),
    )
    state.save("mahoniestraat", [resultaat], 1, state_dir=config.state_dir, unmatched_payments=[betaling])

    resp = client.get("/pand/mahoniestraat/betalingen")
    tekst = resp.get_data(as_text=True)
    assert "Niet-gekoppelde inkomende betalingen" in tekst
    assert "M Poncea Andronescu" in tekst
    assert "Huur juli bg-straatkant" in tekst
    assert "24-07-2026" in tekst


def test_oude_cache_zonder_lijst_geeft_geen_fout(app_client):
    # Simuleert een cache-bestand van vóór deze aanpassing (alleen het
    # aantal, geen lijst) - mag niet crashen, toont dan gewoon geen tabel.
    client, config = app_client
    tenant = Tenant(row_index=2, naam="Miruna", kamer="bg-straatkant", verwacht_bedrag=Decimal("650.00"))
    resultaat = TenantResult(tenant=tenant, ontvangen_bedrag=Decimal("0"), status=Status.NIET_ONTVANGEN)
    state.save("mahoniestraat", [resultaat], 1, state_dir=config.state_dir)  # geen unmatched_payments

    resp = client.get("/pand/mahoniestraat/betalingen")
    assert resp.status_code == 200
    assert "Niet-gekoppelde inkomende betalingen" not in resp.get_data(as_text=True)
