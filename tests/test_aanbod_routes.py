"""Integratietests voor de publieke aanbodpagina + aanmeldformulier, en de
admin-kant (aanbod beheren, aanmeldingen-overzicht), met nep-Sheet/Drive-clients."""
import io
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Tenant
from webapp.app import create_app

KAMER_BESCHIKBAAR = Tenant(
    row_index=2, naam="", kamer="1", verwacht_bedrag=Decimal("650.00"),
    beschikbaar=True, advertentie_omschrijving="A nice room", advertentie_map_id="map-1",
)
KAMER_VERHUURD = Tenant(
    row_index=3, naam="Jan Jansen", kamer="2", verwacht_bedrag=Decimal("700.00"), beschikbaar=False,
)


class FakeSheetClient:
    def __init__(self, _config, pand):
        self.pand = pand
        self.aanmeldingen = []

    def get_kamers(self):
        return [KAMER_BESCHIKBAAR, KAMER_VERHUURD]

    def get_geschiedenis(self, kamer):
        return []

    def update_aanbod(self, row_index, beschikbaar, omschrijving, map_id):
        pass

    def add_aanmelding(self, kamer, aanmelding):
        self.aanmeldingen.append((kamer, aanmelding))

    def get_aanmeldingen(self):
        return [[a.naam, a.email] for _kamer, a in self.aanmeldingen]

    def wis_aanmeldingen(self):
        self.aanmeldingen = []


_fake_sheet_singleton = {}


def _fake_sheet_factory(config, pand):
    if pand.slug not in _fake_sheet_singleton:
        _fake_sheet_singleton[pand.slug] = FakeSheetClient(config, pand)
    return _fake_sheet_singleton[pand.slug]


class FakeDriveClient:
    def __init__(self, _config, _pand):
        pass

    def list_bestanden(self, folder_id):
        if folder_id == "map-1":
            return [_FakeBestand("foto.jpg", "image/jpeg")]
        return []

    def vind_of_maak_map(self, naam, folder_id=None):
        return "nieuwe-map-id"

    def upload_bestand(self, naam, mimetype, inhoud, folder_id=None):
        return "nieuw-bestand-id"

    def download_bestand(self, file_id):
        return "foto.jpg", "image/jpeg", b"fake-image-bytes"

    def verwijder_bestand(self, file_id):
        pass


class _FakeBestand:
    def __init__(self, naam, mimetype):
        self.id = "file-1"
        self.naam = naam
        self.mimetype = mimetype


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    _fake_sheet_singleton.clear()
    monkeypatch.setattr(appmodule, "SheetClient", _fake_sheet_factory)
    monkeypatch.setattr(appmodule, "DriveClient", FakeDriveClient)

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "google_drive_folder_id": "root-folder", "bunq_rekening_iban": "NL81BUNQ2163127125"},
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
    return app.test_client()


VOLLEDIG_FORMULIER = {
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+31612345678",
    "current_address": "Somestreet 1, Rotterdam",
    "study_program": "Computer Science",
    "student_number": "123456",
    "desired_start_date": "2026-09-01",
    "desired_contract_duration": "12 months",
    "income_source": "Parents",
    "income_amount": "1200",
    "guarantor": "Yes",
    "viewing_preference": "in_person",
    "agree_rules": "on",
}


def test_aanbod_overzicht_toont_alleen_beschikbare_kamers(app_client):
    resp = app_client.get("/aanbod")
    assert resp.status_code == 200
    assert b"Mahoniestraat 15" in resp.data
    assert b"room 1" in resp.data
    assert b"room 2" not in resp.data


def test_aanbod_detail_van_verhuurde_kamer_geeft_404(app_client):
    resp = app_client.get("/aanbod/mahoniestraat/2")
    assert resp.status_code == 404


def test_aanbod_detail_van_beschikbare_kamer_werkt(app_client):
    resp = app_client.get("/aanbod/mahoniestraat/1")
    assert resp.status_code == 200
    assert b"A nice room" in resp.data
    assert b"Apply for this room" in resp.data


def test_aanbod_media_alleen_voor_bekende_bestanden(app_client):
    ok = app_client.get("/aanbod/mahoniestraat/1/media/file-1")
    assert ok.status_code == 200
    onbekend = app_client.get("/aanbod/mahoniestraat/1/media/ander-bestand")
    assert onbekend.status_code == 404


def test_apply_form_zonder_verplichte_velden_geeft_fout(app_client):
    resp = app_client.post("/aanbod/mahoniestraat/1/apply", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert b"Please fill in" in resp.data


def test_apply_form_volledig_ingevuld_slaagt(app_client):
    data = dict(VOLLEDIG_FORMULIER)
    data["study_proof"] = (io.BytesIO(b"fake-pdf-bytes"), "enrollment.pdf")
    resp = app_client.post("/aanbod/mahoniestraat/1/apply", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Thank you for your application" in resp.data
    sheet = _fake_sheet_singleton["mahoniestraat"]
    assert len(sheet.aanmeldingen) == 1
    kamer, aanmelding = sheet.aanmeldingen[0]
    assert kamer == "1"
    assert aanmelding.naam == "Jane Doe"
    assert aanmelding.bewijs_inschrijving_link.startswith("https://drive.google.com/")


def test_apply_form_op_verhuurde_kamer_geeft_404(app_client):
    resp = app_client.get("/aanbod/mahoniestraat/2/apply")
    assert resp.status_code == 404


def test_kamer_aanbod_beheren_vereist_login(app_client):
    resp = app_client.get("/pand/mahoniestraat/kamers/1/aanbod", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_kamer_aanbod_beheren_toont_media_en_omschrijving(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.get("/pand/mahoniestraat/kamers/1/aanbod")
    assert resp.status_code == 200
    assert b"A nice room" in resp.data
    assert b"foto.jpg" in resp.data


def test_kamer_aanbod_thumbnail_wijst_naar_inline_route_niet_naar_download(app_client):
    # Regressietest: de <img> op deze pagina moet naar een inline-route wijzen.
    # Eerder wees hij naar documenten_download, die Content-Disposition: attachment
    # meestuurt - daardoor tonen browsers geen thumbnail, alleen een gebroken icoon.
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.get("/pand/mahoniestraat/kamers/1/aanbod")
    body = resp.get_data(as_text=True)
    assert "/aanbod/file-1/weergeven" in body
    assert "/documenten/file-1/download" not in body


def test_kamer_aanbod_media_toont_inline_zonder_attachment_header(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.get("/pand/mahoniestraat/kamers/1/aanbod/file-1/weergeven")
    assert resp.status_code == 200
    assert resp.data == b"fake-image-bytes"
    assert resp.mimetype == "image/jpeg"
    assert "Content-Disposition" not in resp.headers


def test_kamer_aanbod_media_onbekend_bestand_geeft_404(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.get("/pand/mahoniestraat/kamers/1/aanbod/onbekend-id/weergeven")
    assert resp.status_code == 404


def test_aanmeldingen_overzicht_en_wissen(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    data = dict(VOLLEDIG_FORMULIER)
    data["study_proof"] = (io.BytesIO(b"fake-pdf-bytes"), "enrollment.pdf")
    app_client.post("/aanbod/mahoniestraat/1/apply", data=data, content_type="multipart/form-data")

    resp = app_client.get("/pand/mahoniestraat/aanmeldingen")
    assert b"Jane Doe" in resp.data

    app_client.post("/pand/mahoniestraat/aanmeldingen/wissen")
    resp = app_client.get("/pand/mahoniestraat/aanmeldingen")
    assert b"Jane Doe" not in resp.data
    assert b"Nog geen aanmeldingen" in resp.data
