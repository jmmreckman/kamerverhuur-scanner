"""Tests dat een falende upload (bv. een schijffout of een netwerkfout naar
Google Drive) een nette foutmelding geeft in plaats van een onbeholpen
Internal Server Error."""
import json
from decimal import Decimal
from io import BytesIO

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Tenant
from webapp.app import create_app

KAMER_1 = Tenant(
    row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"),
    beschikbaar=True,
)


class FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return [KAMER_1]

    def update_aanbod(self, *args, **kwargs):
        pass

    def add_aanmelding(self, *args, **kwargs):
        pass


class FalendeLokaleMediaClient:
    """Simuleert een schijffout bij het opslaan van een lokaal bestand."""
    def __init__(self, _config, _pand, _categorie):
        pass

    def upload_bestand(self, *args, **kwargs):
        raise OSError("simulated schijffout (bv. schijf vol)")

    def list_bestanden(self, *args, **kwargs):
        return []


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(appmodule, "LokaleMediaClient", FalendeLokaleMediaClient)

    def _falende_upload_bestand(*args, **kwargs):
        raise appmodule.drive_browse.DriveBrowseError("simulated Google Drive-fout (bv. time-out bij een groot bestand)")

    monkeypatch.setattr(appmodule.drive_browse, "upload_bestand", _falende_upload_bestand)
    monkeypatch.chdir(tmp_path)

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
        rclone_remote="gdrive:vastgoed",
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client


def test_falende_aanbod_upload_geeft_nette_foutmelding_geen_500(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/aanbod/upload",
        data={"bestand": (BytesIO(b"fake-image-bytes"), "foto.jpg")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "mislukt" in resp.get_data(as_text=True).lower()


def test_falende_documenten_upload_geeft_nette_foutmelding_geen_500(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/documenten/upload",
        data={"bestand": (BytesIO(b"fake-doc-bytes"), "document.pdf")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "mislukt" in resp.get_data(as_text=True).lower()
