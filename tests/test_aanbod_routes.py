"""Integratietests voor de publieke aanbodpagina + aanmeldformulier, en de
admin-kant (aanbod beheren, aanmeldingen-overzicht), met een nep-Sheetclient
en lokale mediaopslag (tmp_path) in plaats van Google Drive."""
import io
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.lokale_media import LokaleMediaClient
from kamerverhuur_scanner.models import Pand, Tenant
from webapp.app import create_app

KAMER_BESCHIKBAAR = Tenant(
    row_index=2, naam="", kamer="1", verwacht_bedrag=Decimal("650.00"),
    beschikbaar=True, advertentie_omschrijving="A nice room",
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
        # zelfde kolomvolgorde als SheetClient.add_aanmelding()
        return [
            [
                "10-07-2026", kamer, a.naam, a.email, a.telefoon, a.huidig_adres, a.studie,
                a.studentnummer, a.gewenste_ingangsdatum, a.gewenste_huurduur, a.inkomstenbron,
                a.inkomsten_bedrag, a.borgsteller, a.bezichtiging, a.videobel_nummer,
                a.bewijs_inschrijving_link, a.borgsteller_naam, a.borgsteller_relatie, a.borgsteller_email,
            ]
            for kamer, a in self.aanmeldingen
        ]

    def wis_aanmeldingen(self):
        self.aanmeldingen = []


_fake_sheet_singleton = {}


def _fake_sheet_factory(config, pand):
    if pand.slug not in _fake_sheet_singleton:
        _fake_sheet_singleton[pand.slug] = FakeSheetClient(config, pand)
    return _fake_sheet_singleton[pand.slug]


_file_id = {}


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
    )
    pand = Pand(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="fake",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        google_drive_folder_id=None, bunq_rekening_iban="NL81BUNQ2163127125",
    )
    _file_id["1"] = LokaleMediaClient(config, pand, "aanbod").upload_bestand(
        "1", "foto.jpg", "image/jpeg", b"fake-image-bytes"
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
    "guarantor_name": "John Doe",
    "guarantor_relation": "Father",
    "guarantor_email": "john@example.com",
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
    ok = app_client.get(f"/aanbod/mahoniestraat/1/media/{_file_id['1']}")
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
    assert aanmelding.bewijs_inschrijving_link.startswith("/pand/mahoniestraat/aanmeldingen/bewijs/1/")


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
    assert f"/aanbod/{_file_id['1']}/weergeven" in body
    assert f"/documenten/{_file_id['1']}/download" not in body


def test_kamer_aanbod_media_toont_inline_zonder_attachment_header(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.get(f"/pand/mahoniestraat/kamers/1/aanbod/{_file_id['1']}/weergeven")
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
    body = resp.get_data(as_text=True)
    assert "Jane Doe" in body
    # "Contract maken" moet ALLE gegevens van de aanmelding (incl. borgsteller) meegeven
    assert "huurder_naam=Jane+Doe" in body
    assert "studentnummer=123456" in body
    assert "studierichting=Computer+Science" in body
    assert "email=jane@example.com" in body
    assert "borgsteller_naam=John+Doe" in body
    assert "borgsteller_relatie=Father" in body
    assert "borgsteller_email=john@example.com" in body

    app_client.post("/pand/mahoniestraat/aanmeldingen/wissen")
    resp = app_client.get("/pand/mahoniestraat/aanmeldingen")
    assert b"Jane Doe" not in resp.data
    assert b"Nog geen aanmeldingen" in resp.data
