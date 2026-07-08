"""Tests voor 'Mail het hele huishouden': stuurt dezelfde mail apart naar
elke huidige huurder van een pand (bv. aankondiging taxateur/lekkage)."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.mailer import MailError
from kamerverhuur_scanner.models import Tenant
from webapp.app import create_app

KAMER_1 = Tenant(row_index=2, naam="Luisa", kamer="1", verwacht_bedrag=Decimal("650.00"), email="luisa@example.com")
KAMER_2 = Tenant(row_index=3, naam="Vladislav", kamer="2", verwacht_bedrag=Decimal("650.00"), email="vlad@example.com")
KAMER_ZONDER_MAIL = Tenant(row_index=4, naam="Piet", kamer="3", verwacht_bedrag=Decimal("650.00"))
KAMER_LEEG = Tenant(row_index=5, naam="", kamer="4", verwacht_bedrag=Decimal("650.00"))


class FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_tenants(self):
        return [KAMER_1, KAMER_2, KAMER_ZONDER_MAIL]

    def get_kamers(self):
        return [KAMER_1, KAMER_2, KAMER_ZONDER_MAIL]


@pytest.fixture
def verstuurde_mails(monkeypatch):
    verstuurd = []

    def _fake_verstuur_email(config, aan, onderwerp, tekst, bcc=None):
        verstuurd.append({"aan": aan, "onderwerp": onderwerp, "tekst": tekst, "bcc": bcc})

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
         "google_drive_folder_id": None, "bunq_rekening_iban": "NL81BUNQ2163127125",
         "extra_bcc": ["justin@example.com"]},
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
        email_bcc=["eigenaar@example.com"],
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client


def test_formulier_toont_ontvangers_en_mist_lijst(app_client):
    resp = app_client.get("/pand/mahoniestraat/huurders/mailen")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Luisa" in body
    assert "Vladislav" in body
    assert "Piet" in body  # staat in de "geen e-mailadres bekend"-lijst


def test_versturen_gaat_apart_naar_elke_huurder_met_mail(app_client, verstuurde_mails):
    resp = app_client.post(
        "/pand/mahoniestraat/huurders/mailen",
        data={"onderwerp": "Taxateur langs", "tekst": "Beste bewoners, ..."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert len(verstuurde_mails) == 2  # Luisa en Vladislav, niet Piet (geen mailadres)
    ontvangers = {m["aan"] for m in verstuurde_mails}
    assert ontvangers == {"luisa@example.com", "vlad@example.com"}
    for mail in verstuurde_mails:
        assert mail["onderwerp"] == "Taxateur langs"
        assert mail["bcc"] == ["eigenaar@example.com", "justin@example.com"]


def test_versturen_meldt_ontbrekende_mailadressen(app_client, verstuurde_mails):
    resp = app_client.post(
        "/pand/mahoniestraat/huurders/mailen",
        data={"onderwerp": "Taxateur langs", "tekst": "Beste bewoners, ..."},
        follow_redirects=True,
    )
    body = resp.get_data(as_text=True)
    assert "verstuurd naar 2 huurder" in body.lower()
    assert "piet" in body.lower()


def test_leeg_onderwerp_of_tekst_wordt_geweigerd(app_client, verstuurde_mails):
    resp = app_client.post(
        "/pand/mahoniestraat/huurders/mailen",
        data={"onderwerp": "", "tekst": "Beste bewoners, ..."},
    )
    assert resp.status_code == 200
    assert verstuurde_mails == []
    assert "verplicht" in resp.get_data(as_text=True).lower()


def test_mailerror_bij_1_huurder_stopt_de_rest_niet(app_client, monkeypatch):
    import webapp.app as appmodule

    def _wisselvallige_mailer(config, aan, onderwerp, tekst, bcc=None):
        if aan == "luisa@example.com":
            raise MailError("SMTP tijdelijk niet bereikbaar")

    monkeypatch.setattr(appmodule, "verstuur_email", _wisselvallige_mailer)

    resp = app_client.post(
        "/pand/mahoniestraat/huurders/mailen",
        data={"onderwerp": "Taxateur langs", "tekst": "Beste bewoners, ..."},
        follow_redirects=True,
    )
    body = resp.get_data(as_text=True)
    assert "verstuurd naar 1 huurder" in body.lower()
    assert "mislukt" in body.lower()
    assert "luisa" in body.lower()
