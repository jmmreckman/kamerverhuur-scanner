"""Tests voor de contractroutes: nieuw contract genereren (incl. terugschrijven
naar de Huurders-sheet) en PDF-download."""
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

    def update_kamer(self, **kwargs):
        FakeSheetClient.laatste_update = kwargs


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    monkeypatch.chdir(tmp_path)

    contracten_dir = tmp_path / "gegenereerde_contracten"
    import webapp.contracts as contracts
    monkeypatch.setattr(contracts, "BASIS_OUTPUT_DIR", contracten_dir)

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "google_drive_folder_id": None, "bunq_rekening_iban": "NL81BUNQ2163127125",
         "postcode": "3077WD", "plaats": "Rotterdam", "rekeninghouder_naam": "JMM Reckman",
         "gedeelde_ruimtes": "keuken, badkamer, tuin",
         "verhuurders": [{"naam": "Jurian Reckman", "adres": "Batavierenplantsoen 33, Haarlem"}]},
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


def test_contract_nieuw_toont_kamerselectie(app_client):
    resp = app_client.get("/pand/mahoniestraat/contracten/nieuw")
    assert resp.status_code == 200
    assert "Kamer 1" in resp.get_data(as_text=True)


def test_contract_genereren_schrijft_gegevens_terug_naar_sheet(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/contracten/nieuw",
        data={
            "kamer": "1", "huurder_naam": "Bence Neumayer", "geboortedatum": "27-11-2000",
            "geboorteplaats": "Tatabánya, Hungary", "studentnummer": "1124601",
            "studierichting": "Consultancy", "borgsteller_naam": "Tamás Neumayer",
            "borgsteller_relatie": "Vader", "kale_huurprijs": "711,49", "servicekosten": "207,51",
            "huurprijs": "919,00", "borg": "1000,00", "aantal_bewoners": "6",
            "ingangsdatum": "2026-07-01", "einddatum": "2028-07-01", "bijzonderheden": "",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    update = FakeSheetClient.laatste_update
    assert update["row_index"] == 2
    assert update["geboortedatum"] == "27-11-2000"
    assert update["studentnummer"] == "1124601"
    assert update["borgsteller_naam"] == "Tamás Neumayer"
    assert update["contract_startdatum"] == "2026-07-01"


def test_contract_bekijken_en_pdf_downloaden(app_client):
    app_client.post(
        "/pand/mahoniestraat/contracten/nieuw",
        data={
            "kamer": "1", "huurder_naam": "Bence Neumayer", "huurprijs": "919,00",
            "ingangsdatum": "2026-07-01",
        },
    )
    resp = app_client.get("/pand/mahoniestraat/contracten")
    body = resp.get_data(as_text=True)
    assert "Download als PDF" in body

    # bestandsnaam uit de link halen
    import re
    match = re.search(r'contracten/([^/"]+\.html)/pdf', body)
    assert match, body
    bestandsnaam = match.group(1)

    pdf_resp = app_client.get(f"/pand/mahoniestraat/contracten/{bestandsnaam}/pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.mimetype == "application/pdf"
    assert pdf_resp.data.startswith(b"%PDF")
