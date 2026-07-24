"""Route-tests voor de zelfbediening-Mailvoorkeurenpagina, en een end-to-end
test dat een opt-out een BCC-adres echt uit een verstuurde mail filtert."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Tenant
from webapp.app import create_app

KAMER_1 = Tenant(row_index=2, naam="Luisa", kamer="1", verwacht_bedrag=Decimal("650.00"), email="luisa@example.com")


class FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_tenants(self):
        return [KAMER_1]

    def get_kamers(self):
        return [KAMER_1]

    def get_recent_vertrokken_huurders(self, dagen=31):
        return []

    def add_communicatie(self, kamer, huurder_naam, richting, onderwerp, tekst):
        pass


@pytest.fixture
def opzet(tmp_path, monkeypatch):
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
    config = Config(
        google_service_account_file="fake.json", properties_file=str(properties_file),
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file=str(users_file), flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14,
        smtp_host="smtp.example.com", smtp_port=587, smtp_username="info@steenhub.nl",
        smtp_password="geheim", smtp_from_email="info@steenhub.nl", smtp_from_naam="Steenhub",
        email_bcc=["beheerder@example.com", "eigenaar@example.com"],
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client, users_file


@pytest.fixture
def verstuurde_mails(monkeypatch):
    verstuurd = []

    def _fake_verstuur_email(config, aan, onderwerp, tekst, bcc=None, **kwargs):
        verstuurd.append({"aan": aan, "onderwerp": onderwerp, "tekst": tekst, "bcc": bcc})

    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "verstuur_email", _fake_verstuur_email)
    return verstuurd


def test_pagina_vereist_login(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "bunq_rekening_iban": "NL81BUNQ2163127125"},
    ]))
    users_file = tmp_path / "users.json"
    users_file.write_text("{}")
    config = Config(
        google_service_account_file="fake.json", properties_file=str(properties_file),
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file=str(users_file), flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14,
    )
    client = create_app(config).test_client()
    resp = client.get("/account/mail-voorkeuren", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_pagina_toont_alle_types_standaard_aangevinkt(opzet):
    client, _users_file = opzet
    resp = client.get("/account/mail-voorkeuren")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Mail het hele huishouden" in body
    assert "Nieuwe aanmeldingen" in body
    assert body.count('name="voorkeur_huishouden" checked') == 1


def test_opslaan_bewaart_email_en_voorkeuren(opzet):
    client, users_file = opzet
    resp = client.post(
        "/account/mail-voorkeuren",
        data={"email": "beheerder@example.com", "voorkeur_communicatie": "on"},  # huishouden bewust niet aangevinkt
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "opgeslagen" in resp.get_data(as_text=True).lower()

    opgeslagen = json.loads(users_file.read_text())
    assert opgeslagen["beheerder"]["email"] == "beheerder@example.com"
    assert opgeslagen["beheerder"]["mail_voorkeuren"]["huishouden"] is False
    assert opgeslagen["beheerder"]["mail_voorkeuren"]["communicatie"] is True


def test_ongeldig_emailadres_wordt_geweigerd(opzet):
    client, users_file = opzet
    resp = client.post("/account/mail-voorkeuren", data={"email": "geen-email-adres"})
    assert resp.status_code == 200
    assert "geldig e-mailadres" in resp.get_data(as_text=True).lower()
    assert "email" not in json.loads(users_file.read_text())["beheerder"]


def test_leeg_emailadres_is_toegestaan_en_maakt_account_weer_los(opzet):
    client, users_file = opzet
    client.post("/account/mail-voorkeuren", data={"email": "beheerder@example.com"})
    client.post("/account/mail-voorkeuren", data={"email": ""})
    opgeslagen = json.loads(users_file.read_text())
    assert opgeslagen["beheerder"]["email"] is None


def test_opt_out_filtert_adres_uit_echte_bcc_verzending(opzet, verstuurde_mails):
    client, users_file = opzet
    # beheerder@example.com meldt zich af voor "huishouden"-mails
    client.post(
        "/account/mail-voorkeuren",
        data={"email": "beheerder@example.com"},  # geen enkele voorkeur_* aangevinkt = alles uit
    )

    client.post(
        "/pand/mahoniestraat/huurders/mailen",
        data={"onderwerp": "Taxateur langs", "tekst": "Beste bewoners, ...", "kamers": ["1"]},
    )

    assert len(verstuurde_mails) == 1
    bcc = verstuurde_mails[0]["bcc"]
    assert "beheerder@example.com" not in bcc
    assert "eigenaar@example.com" in bcc  # geen account, blijft gewoon bcc'en
