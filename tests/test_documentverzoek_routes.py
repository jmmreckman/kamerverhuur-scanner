"""Route-tests voor het opvragen van documenten (ID/paspoort, bewijs van
inkomen/garantsteller) bij de gekozen kandidaat na een bezichtiging: knop +
editable mail vanaf de bezichtigingen-pagina, de publieke uploadpagina, en
de statuspagina voor de beheerder."""
import io
import json
import re
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from webapp.app import create_app


class FakeSheetClient:
    def __init__(self, _config, pand):
        self.pand = pand
        self.bezichtigingen = []

    def get_kamers(self):
        return []

    def add_bezichtiging(self, datum_iso, afspraak):
        self.bezichtigingen.append((datum_iso, dict(afspraak)))

    def get_bezichtigingen(self):
        return [
            [
                datum_iso, a["tijd_start"], a["tijd_eind"], a["kamer"], a["naam"], a["email"],
                a["telefoon"], a["bezichtiging"], a["bel_nummer"], "10-07-2026 12:00",
            ]
            for datum_iso, a in self.bezichtigingen
        ]

    def get_bezichtigingen_met_rijnummer(self):
        return list(enumerate(self.get_bezichtigingen(), start=2))

    def verwijder_bezichtiging(self, rijnummer):
        del self.bezichtigingen[rijnummer - 2]


_fake_sheet_singleton = {}


def _fake_sheet_factory(config, pand):
    if pand.slug not in _fake_sheet_singleton:
        _fake_sheet_singleton[pand.slug] = FakeSheetClient(config, pand)
    return _fake_sheet_singleton[pand.slug]


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    _fake_sheet_singleton.clear()
    monkeypatch.setattr(appmodule, "SheetClient", _fake_sheet_factory)

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
        smtp_host="smtp.example.com", smtp_port=587, smtp_username="info@steenhub.nl",
        smtp_password="geheim", smtp_from_email="info@steenhub.nl", smtp_from_naam="Steenhub",
        email_bcc=["jurian@example.com"], email_bcc_beheerder=["jmmreckman@gmail.com"],
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    client.get("/pand/mahoniestraat/aanmeldingen/bezichtigingen")  # instantieert de FakeSheetClient-singleton
    return client


@pytest.fixture
def verstuurde_mails(monkeypatch):
    verstuurd = []

    def _fake_verstuur_email(config, aan, onderwerp, tekst, bcc=None, **kwargs):
        verstuurd.append({"aan": aan, "onderwerp": onderwerp, "tekst": tekst, "bcc": bcc})

    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "verstuur_email", _fake_verstuur_email)
    return verstuurd


def _voeg_bezichtiging_toe(naam="Jane Doe", email="jane@example.com", kamer="1"):
    sheet = _fake_sheet_singleton["mahoniestraat"]
    sheet.add_bezichtiging("2026-08-01", {
        "tijd_start": "10:00", "tijd_eind": "10:20", "kamer": kamer, "naam": naam,
        "email": email, "telefoon": "+31612345678", "bezichtiging": "In person", "bel_nummer": "",
    })


def _rijnummer(app_client) -> int:
    resp = app_client.get("/pand/mahoniestraat/aanmeldingen/bezichtigingen")
    match = re.search(r'name="rijnummers" value="(\d+)"', resp.get_data(as_text=True))
    assert match
    return int(match.group(1))


def test_documentverzoek_knop_staat_op_bezichtigingen_pagina(app_client):
    _voeg_bezichtiging_toe()
    resp = app_client.get("/pand/mahoniestraat/aanmeldingen/bezichtigingen")
    assert b"Documenten verzoeken" in resp.data


def test_documentverzoek_voorbeeld_vereist_precies_een_selectie(app_client):
    _voeg_bezichtiging_toe()
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtigingen/documenten-verzoeken",
        data={}, follow_redirects=True,
    )
    assert "precies 1 kandidaat" in resp.get_data(as_text=True).lower()


def test_documentverzoek_voorbeeld_zonder_email_geeft_foutmelding(app_client):
    _voeg_bezichtiging_toe(email="")
    rijnummer = _rijnummer(app_client)
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtigingen/documenten-verzoeken",
        data={"rijnummers": str(rijnummer)}, follow_redirects=True,
    )
    assert "geen e-mailadres bekend" in resp.get_data(as_text=True).lower()


def test_documentverzoek_voorbeeld_toont_editable_mail_met_upload_link(app_client):
    _voeg_bezichtiging_toe()
    rijnummer = _rijnummer(app_client)
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtigingen/documenten-verzoeken",
        data={"rijnummers": str(rijnummer)},
    )
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Documents needed" in body
    assert "/documenten/" in body
    assert "Jane Doe" in body


@pytest.mark.usefixtures("verstuurde_mails")
def test_documentverzoek_versturen_mailt_kandidaat_en_redirect_naar_status(app_client, verstuurde_mails):
    _voeg_bezichtiging_toe()
    rijnummer = _rijnummer(app_client)
    voorbeeld = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtigingen/documenten-verzoeken",
        data={"rijnummers": str(rijnummer)},
    )
    body = voorbeeld.get_data(as_text=True)
    sleutel_match = re.search(r'/documentverzoek/([a-z0-9-]+)/versturen', body)
    assert sleutel_match
    sleutel = sleutel_match.group(1)

    resp = app_client.post(
        f"/pand/mahoniestraat/documentverzoek/{sleutel}/versturen",
        data={"onderwerp": "Documents needed - room 1", "tekst": "Please upload your documents."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "verstuurd" in resp.get_data(as_text=True).lower()
    assert len(verstuurde_mails) == 1
    assert verstuurde_mails[0]["aan"] == "jane@example.com"
    assert verstuurde_mails[0]["onderwerp"] == "Documents needed - room 1"


def _maak_verzoek(app_client) -> tuple[str, str]:
    """Maakt een documentverzoek aan en geeft (token, sleutel) terug."""
    _voeg_bezichtiging_toe()
    rijnummer = _rijnummer(app_client)
    voorbeeld = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtigingen/documenten-verzoeken",
        data={"rijnummers": str(rijnummer)},
    )
    body = voorbeeld.get_data(as_text=True)
    token_match = re.search(r'/documenten/([\w-]+)', body)
    sleutel_match = re.search(r'/documentverzoek/([a-z0-9-]+)/versturen', body)
    assert token_match and sleutel_match
    return token_match.group(1), sleutel_match.group(1)


def _maak_verzoek_en_haal_token(app_client) -> str:
    token, _sleutel = _maak_verzoek(app_client)
    return token


def test_documenten_upload_onbekende_token_geeft_404(app_client):
    resp = app_client.get("/documenten/onbekende-token")
    assert resp.status_code == 404


def test_documenten_upload_pagina_toont_uploadvelden(app_client):
    token = _maak_verzoek_en_haal_token(app_client)
    resp = app_client.get(f"/documenten/{token}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "id_bestanden" in body
    assert "inkomen_bestanden" in body


def test_documenten_upload_zonder_bestanden_geeft_foutmelding(app_client):
    token = _maak_verzoek_en_haal_token(app_client)
    resp = app_client.post(f"/documenten/{token}", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "select at least one file" in resp.get_data(as_text=True).lower()


def test_documenten_upload_slaat_bestanden_op_en_toont_bevestiging(app_client, verstuurde_mails):
    token = _maak_verzoek_en_haal_token(app_client)
    resp = app_client.post(
        f"/documenten/{token}",
        data={
            "id_bestanden": (io.BytesIO(b"fake-id-bytes"), "id.jpg"),
            "inkomen_bestanden": (io.BytesIO(b"fake-inkomen-bytes"), "loonstrook.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert "Thank you" in resp.get_data(as_text=True)
    # beheerder krijgt een meldingsmail dat er documenten binnen zijn
    assert len(verstuurde_mails) == 1
    assert verstuurde_mails[0]["aan"] == "jurian@example.com"
    assert "Documents received" in verstuurde_mails[0]["onderwerp"]


def test_documentverzoek_status_toont_geuploade_bestanden(app_client):
    token, sleutel = _maak_verzoek(app_client)
    app_client.post(
        f"/documenten/{token}",
        data={"id_bestanden": (io.BytesIO(b"fake-id-bytes"), "id.jpg")},
        content_type="multipart/form-data",
    )
    resp = app_client.get(f"/pand/mahoniestraat/documentverzoek/{sleutel}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "id.jpg" in body
    assert "Copy of ID/passport" in body


def test_documentverzoek_bestand_download_werkt(app_client):
    token, sleutel = _maak_verzoek(app_client)
    app_client.post(
        f"/documenten/{token}",
        data={"id_bestanden": (io.BytesIO(b"fake-id-bytes"), "id.jpg")},
        content_type="multipart/form-data",
    )
    status = app_client.get(f"/pand/mahoniestraat/documentverzoek/{sleutel}")
    match = re.search(r'/bestand/([\w.-]+)"', status.get_data(as_text=True))
    assert match
    resp = app_client.get(f"/pand/mahoniestraat/documentverzoek/{sleutel}/bestand/{match.group(1)}")
    assert resp.status_code == 200
    assert resp.data == b"fake-id-bytes"


def test_documentverzoek_bestand_onbekend_geeft_404(app_client):
    resp = app_client.get("/pand/mahoniestraat/documentverzoek/onbekende-sleutel/bestand/x")
    assert resp.status_code == 404


def test_documentverzoek_status_onbekende_sleutel_geeft_404(app_client):
    resp = app_client.get("/pand/mahoniestraat/documentverzoek/onbekende-sleutel")
    assert resp.status_code == 404
