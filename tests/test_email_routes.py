"""Integratietests voor de betaalherinnering/ingebrekestelling-knoppen op de
Betalingen-pagina, met een nep-Sheet en een nep-mailer (geen echte SMTP)."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.mailer import MailError
from kamerverhuur_scanner.models import Tenant
from webapp.app import create_app

KAMER_MET_MAIL = Tenant(
    row_index=2, naam="Luisa", kamer="3", verwacht_bedrag=Decimal("650.00"), email="luisa@example.com",
)
KAMER_ZONDER_MAIL = Tenant(
    row_index=3, naam="Piet", kamer="4", verwacht_bedrag=Decimal("650.00"),
)


class FakeSheetClient:
    def __init__(self, _config, pand):
        self.pand = pand

    def get_kamers(self):
        return [KAMER_MET_MAIL, KAMER_ZONDER_MAIL]

    def get_geschiedenis(self, kamer):
        return []


@pytest.fixture
def verstuurde_mails(monkeypatch):
    verstuurd = []

    def _fake_verstuur_email(config, aan, onderwerp, tekst):
        verstuurd.append({"aan": aan, "onderwerp": onderwerp, "tekst": tekst})

    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "verstuur_email", _fake_verstuur_email)
    return verstuurd


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    monkeypatch.chdir(tmp_path)

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "google_drive_folder_id": None, "bunq_rekening_iban": "NL81BUNQ2163127125"},
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


def test_email_voorbeeldscherm_toont_opgestelde_tekst(app_client):
    resp = app_client.get("/pand/mahoniestraat/kamers/3/email/herinnering")
    assert resp.status_code == 200
    assert b"Luisa" in resp.data


def test_email_zonder_adres_stuurt_terug_met_melding(app_client):
    resp = app_client.get("/pand/mahoniestraat/kamers/4/email/herinnering", follow_redirects=True)
    assert resp.status_code == 200
    assert "geen e-mailadres".lower() in resp.get_data(as_text=True).lower()


def test_onbekend_soort_geeft_404(app_client):
    resp = app_client.get("/pand/mahoniestraat/kamers/3/email/onzin")
    assert resp.status_code == 404


def test_versturen_roept_mailer_aan_en_flasht_bevestiging(app_client, verstuurde_mails):
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/3/email/ingebrekestelling",
        data={"onderwerp": "Test onderwerp", "tekst": "Test tekst"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert len(verstuurde_mails) == 1
    assert verstuurde_mails[0]["aan"] == "luisa@example.com"
    assert verstuurde_mails[0]["onderwerp"] == "Test onderwerp"
    assert "verstuurd naar luisa" in resp.get_data(as_text=True).lower()


def test_mailerror_bij_versturen_toont_foutmelding_en_behoudt_formulier(app_client, monkeypatch):
    import webapp.app as appmodule

    def _kapotte_mailer(config, aan, onderwerp, tekst):
        raise MailError("SMTP niet ingesteld")

    monkeypatch.setattr(appmodule, "verstuur_email", _kapotte_mailer)

    resp = app_client.post(
        "/pand/mahoniestraat/kamers/3/email/herinnering",
        data={"onderwerp": "Test onderwerp", "tekst": "Test tekst"},
    )
    assert resp.status_code == 200
    assert "SMTP niet ingesteld" in resp.get_data(as_text=True)
