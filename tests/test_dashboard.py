"""Tests voor de dashboardtegels: huurpenningen ontvangen, aflopende
contracten (met wegklikbare aanzeg-waarschuwingen) en de mail-snelkoppeling."""
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner import state
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Status, Tenant, TenantResult
from webapp.aanzegging import bereken_aanzeg_status
from webapp.app import create_app


def _kamer(kamer="1", naam="Jan", einddatum=None):
    return Tenant(row_index=2, naam=naam, kamer=kamer, verwacht_bedrag=Decimal("650.00"), contract_einddatum=einddatum)


class FakeSheetClient:
    kamers = [_kamer()]

    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return FakeSheetClient.kamers


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    FakeSheetClient.kamers = [_kamer()]

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


def test_geen_aflopende_contracten_toont_geen_tegel(app_client):
    client, _config = app_client
    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "kamers komen binnenkort leeg" in body.lower()


def test_kamer_die_binnen_2_maanden_afloopt_toont_tegel(app_client):
    client, _config = app_client
    einddatum = (date.today() + timedelta(days=30)).strftime("%d-%m-%Y")
    FakeSheetClient.kamers = [_kamer(einddatum=einddatum)]
    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "komt kamer 1" in body.lower()


def test_kamer_die_over_6_maanden_afloopt_toont_geen_tegel(app_client):
    client, _config = app_client
    einddatum = (date.today() + timedelta(days=180)).strftime("%d-%m-%Y")
    FakeSheetClient.kamers = [_kamer(einddatum=einddatum)]
    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "kamers komen binnenkort leeg" in body.lower()


def test_meerdere_aflopende_contracten_krijgen_elk_een_eigen_tegel(app_client):
    client, _config = app_client
    einddatum_1 = (date.today() + timedelta(days=20)).strftime("%d-%m-%Y")
    einddatum_2 = (date.today() + timedelta(days=40)).strftime("%d-%m-%Y")
    FakeSheetClient.kamers = [
        _kamer(kamer="1", naam="Henri", einddatum=einddatum_1),
        _kamer(kamer="2", naam="Matias", einddatum=einddatum_2),
    ]
    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "komt kamer 1" in body.lower()
    assert "komt kamer 2" in body.lower()
    assert "+ 1 meer" not in body.lower()


def test_opnieuw_controleren_knop_staat_niet_meer_op_dashboard(app_client):
    client, config = app_client
    resultaat = TenantResult(tenant=_kamer(), ontvangen_bedrag=Decimal("650.00"), status=Status.BETAALD)
    state.save("mahoniestraat", [resultaat], 0, state_dir=config.state_dir)

    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "opnieuw controleren" not in body.lower()


def test_mail_snelkoppeling_staat_altijd_op_dashboard(app_client):
    client, _config = app_client
    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "/pand/mahoniestraat/huurders/mailen" in body


def test_aanzegging_afhandelen_verbergt_waarschuwing_maar_niet_de_leegkomt_tegel(app_client):
    client, config = app_client
    # binnen de wettelijke aanzegtermijn (1-3 maanden voor einddatum)
    einddatum = (date.today() + timedelta(days=45)).strftime("%d-%m-%Y")
    FakeSheetClient.kamers = [_kamer(einddatum=einddatum)]

    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "aangezegd moeten worden" in body.lower()
    assert "komt kamer 1" in body.lower()

    status = bereken_aanzeg_status(einddatum)
    client.post("/pand/mahoniestraat/dashboard/aanzegging-afhandelen", data={
        "kamer": "1", "einddatum": status.einddatum.isoformat(),
    })

    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "aangezegd moeten worden" not in body.lower()
    # het wegklikken van de wettelijke aanzegging betekent niet dat er al een
    # nieuwe huurder is - de "komt leeg"-tegel moet dus gewoon blijven staan
    assert "komt kamer 1" in body.lower()
    assert "kamers komen binnenkort leeg" not in body.lower()

    # de markering staat ook echt in de state-map, niet alleen in de sessie
    assert state.aanzegging_is_afgehandeld("mahoniestraat", "1", status.einddatum.isoformat(), config.state_dir)


def test_huurpenningen_tegel_toont_betaalstatus(app_client):
    client, config = app_client
    resultaat = TenantResult(tenant=_kamer(), ontvangen_bedrag=Decimal("650.00"), status=Status.BETAALD)
    state.save("mahoniestraat", [resultaat], 0, state_dir=config.state_dir)

    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "1 / 1" in body
    assert "huurpenningen ontvangen" in body.lower()


def test_huurpenningen_en_euro_tegels_linken_naar_betalingen(app_client):
    client, config = app_client
    resultaat = TenantResult(tenant=_kamer(), ontvangen_bedrag=Decimal("650.00"), status=Status.BETAALD)
    state.save("mahoniestraat", [resultaat], 0, state_dir=config.state_dir)

    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    betalingen_link = '/pand/mahoniestraat/betalingen'
    # allebei de tegels moeten als link naar Betalingen wijzen
    assert body.count(f'<a class="stat-card" href="{betalingen_link}"') == 2
