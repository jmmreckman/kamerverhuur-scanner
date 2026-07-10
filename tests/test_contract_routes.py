"""Tests voor de contractroutes: nieuw contract genereren (incl. terugschrijven
naar de Huurders-sheet), PDF-download en het mailen van het concept-contract."""
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Tenant
from webapp.app import create_app

KAMER_1 = Tenant(row_index=2, naam="Bence Neumayer", kamer="1", verwacht_bedrag=Decimal("919.00"))


class FakeSheetClient:
    laatste_update = None
    archiveer_aangeroepen_met = None

    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return [KAMER_1]

    def get_tenants(self):
        return [KAMER_1]

    def update_kamer(self, **kwargs):
        FakeSheetClient.laatste_update = kwargs

    def archiveer_vertrokken_huurder(self, kamer):
        FakeSheetClient.archiveer_aangeroepen_met = kamer

    def get_recent_vertrokken_huurders(self):
        return []


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
         "gedeelde_ruimtes": "keuken, badkamer, tuin", "extra_bcc": ["justin@example.com"],
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
        smtp_host="smtp.example.com", smtp_port=587, smtp_username="info@steenhub.nl",
        smtp_password="geheim", smtp_from_email="info@steenhub.nl", smtp_from_naam="Steenhub",
        email_bcc=["jurian@example.com"],
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
    FakeSheetClient.archiveer_aangeroepen_met = None
    resp = app_client.post(
        "/pand/mahoniestraat/contracten/nieuw",
        data={
            "kamer": "1", "huurder_naam": "Bence Neumayer", "geboortedatum": "27-11-2000",
            "geboorteplaats": "Tatabánya, Hungary", "studentnummer": "1124601",
            "studierichting": "Consultancy", "borgsteller_naam": "Tamás Neumayer",
            "borgsteller_relatie": "Vader", "kale_huurprijs": "711,49", "servicekosten": "207,51",
            "huurprijs": "919,00", "borg": "1000,00", "aantal_bewoners": "6",
            "ingangsdatum": "2026-07-01", "einddatum": "2028-07-01", "bijzonderheden": "",
            "schrijf_terug_naar_sheet": "on",
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
    # zelfde huurder, alleen bijgewerkte gegevens - geen "vertrokken huurder" archivering
    assert FakeSheetClient.archiveer_aangeroepen_met is None


def test_contract_genereren_voor_andere_huurder_archiveert_de_vertrekkende(app_client):
    FakeSheetClient.archiveer_aangeroepen_met = None
    resp = app_client.post(
        "/pand/mahoniestraat/contracten/nieuw",
        data={
            "kamer": "1", "huurder_naam": "Nieuwe Huurder", "huurprijs": "919,00",
            "ingangsdatum": "2026-07-01", "schrijf_terug_naar_sheet": "on",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    gearchiveerd = FakeSheetClient.archiveer_aangeroepen_met
    assert gearchiveerd is not None
    assert gearchiveerd.naam == "Bence Neumayer"  # de oude huurder van kamer 1, niet de nieuwe


def test_contract_genereren_zonder_vinkje_laat_sheet_ongemoeid(app_client):
    FakeSheetClient.laatste_update = None
    resp = app_client.post(
        "/pand/mahoniestraat/contracten/nieuw",
        data={
            "kamer": "1", "huurder_naam": "Bence Neumayer", "huurprijs": "919,00",
            "ingangsdatum": "2026-07-01",
            # geen "schrijf_terug_naar_sheet" veld - alsof het vinkje is uitgezet
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert FakeSheetClient.laatste_update is None


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


def _genereer_en_haal_bestandsnaam(app_client, **overrides):
    data = {
        "kamer": "1", "huurder_naam": "Bence Neumayer", "huurprijs": "919,00",
        "ingangsdatum": "2026-07-01", "borg": "1000,00", "email": "bence@example.com",
    }
    data.update(overrides)
    app_client.post("/pand/mahoniestraat/contracten/nieuw", data=data)
    resp = app_client.get("/pand/mahoniestraat/contracten")
    import re
    match = re.search(r'contracten/([^/"]+\.html)/pdf', resp.get_data(as_text=True))
    assert match
    return match.group(1)


def test_contract_genereren_stuurt_direct_door_naar_mailen(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/contracten/nieuw",
        data={
            "kamer": "1", "huurder_naam": "Bence Neumayer", "huurprijs": "919,00",
            "ingangsdatum": "2026-07-01", "email": "bence@example.com",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/mailen" in resp.headers["Location"]


def test_contract_mailen_vult_emailadres_en_engelse_tekst_voor(app_client):
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    resp = app_client.get(f"/pand/mahoniestraat/contracten/{bestandsnaam}/mailen")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'value="bence@example.com"' in body
    assert "DocHub" in body
    assert "Bold" in body


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_contract_mailen_verstuurt_met_pdf_bijlage_en_cc(mock_smtp_cls, app_client):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)

    resp = app_client.post(
        f"/pand/mahoniestraat/contracten/{bestandsnaam}/mailen",
        data={"aan": "bence@example.com", "onderwerp": "Draft rental agreement", "tekst": "Dear Bence, ..."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "gemaild naar bence@example.com" in resp.get_data(as_text=True)

    verzonden_bericht = smtp_instance.send_message.call_args[0][0]
    assert verzonden_bericht["To"] == "bence@example.com"
    # zowel het pand-specifieke extra_bcc (Justin) als het algemene EMAIL_BCC
    # (Jurian) horen zichtbaar in CC te staan - niet als BCC.
    assert verzonden_bericht["Cc"] == "jurian@example.com, justin@example.com"
    bijlagen = list(verzonden_bericht.iter_attachments())
    assert len(bijlagen) == 1
    assert bijlagen[0].get_content_type() == "application/pdf"
    assert bijlagen[0].get_content().startswith(b"%PDF")


def test_contract_mailen_zonder_emailadres_geeft_foutmelding(app_client):
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    resp = app_client.post(
        f"/pand/mahoniestraat/contracten/{bestandsnaam}/mailen",
        data={"aan": "", "onderwerp": "Onderwerp", "tekst": "Tekst"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "vul een e-mailadres" in resp.get_data(as_text=True).lower()


def test_contract_mailen_onbekend_bestand_geeft_404(app_client):
    resp = app_client.get("/pand/mahoniestraat/contracten/bestaat-niet.html/mailen")
    assert resp.status_code == 404


# --- Contractsjabloon aanpassen (alleen voor beheerders met alle_panden) ---


def test_contractsjabloon_bewerken_toont_standaardtekst(app_client):
    import webapp.contracts as contracts
    resp = app_client.get("/beheer/contractsjabloon")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Article 1" in body  # uit de standaardtekst
    assert "Terugzetten naar standaardsjabloon" not in body  # nog geen aanpassing actief


def test_contractsjabloon_opslaan_en_gebruikt_bij_nieuw_contract(app_client):
    resp = app_client.post(
        "/beheer/contractsjabloon",
        data={"sjabloon": "<p>Speciaal artikel voor {{ huurder_naam }}, kamer {{ kamer }}</p>"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "opgeslagen" in resp.get_data(as_text=True).lower()

    # een nieuw contract gebruikt nu meteen het aangepaste sjabloon
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    contract_resp = app_client.get(f"/pand/mahoniestraat/contracten/{bestandsnaam}")
    assert "Speciaal artikel voor Bence Neumayer, kamer 1" in contract_resp.get_data(as_text=True)

    # en het bewerkscherm toont nu de "terugzetten"-optie
    bewerk_resp = app_client.get("/beheer/contractsjabloon")
    assert "Terugzetten naar standaardsjabloon" in bewerk_resp.get_data(as_text=True)


def test_contractsjabloon_ongeldige_syntax_wordt_niet_opgeslagen(app_client):
    resp = app_client.post(
        "/beheer/contractsjabloon",
        data={"sjabloon": "<p>{% if kapot %}geen endif</p>"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "ongeldige" in resp.get_data(as_text=True).lower()

    bewerk_resp = app_client.get("/beheer/contractsjabloon")
    assert "Terugzetten naar standaardsjabloon" not in bewerk_resp.get_data(as_text=True)


def test_contractsjabloon_terugzetten(app_client):
    app_client.post("/beheer/contractsjabloon", data={"sjabloon": "<p>Aangepast</p>"})
    resp = app_client.post("/beheer/contractsjabloon/terugzetten", follow_redirects=True)
    assert resp.status_code == 200
    assert "teruggezet" in resp.get_data(as_text=True).lower()
    bewerk_resp = app_client.get("/beheer/contractsjabloon")
    assert "Terugzetten naar standaardsjabloon" not in bewerk_resp.get_data(as_text=True)


def test_contractsjabloon_vereist_alle_panden_toegang(app_client, tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "beheerder": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
        "justin": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": False, "panden": ["mahoniestraat"]},
    }))
    app_client.get("/logout")
    app_client.post("/login", data={"username": "justin", "password": "geheim123"})
    resp = app_client.get("/beheer/contractsjabloon", follow_redirects=True)
    assert "geen toegang" in resp.get_data(as_text=True).lower()
