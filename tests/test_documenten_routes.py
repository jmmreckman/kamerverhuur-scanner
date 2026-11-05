"""Route-tests voor de Documenten-pagina - bladert door dezelfde
automatisch aangemaakte "Steenhub <pandnaam>"-Drive-map als drive_sync.py,
via drive_browse.py (rclone). rclone zelf wordt hier nooit echt aangeroepen,
alleen de drive_browse-functies worden gemonkeypatcht."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner import drive_browse
from kamerverhuur_scanner.config import Config
from webapp.app import create_app


class FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return []


def _bouw_app_client(tmp_path, monkeypatch, rclone_remote="gdrive:vastgoed"):
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
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, rclone_remote=rclone_remote,
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    return _bouw_app_client(tmp_path, monkeypatch)


def test_documenten_zonder_rclone_remote_toont_niet_ingesteld(tmp_path, monkeypatch):
    client = _bouw_app_client(tmp_path, monkeypatch, rclone_remote=None)
    resp = client.get("/pand/mahoniestraat/documenten")
    assert resp.status_code == 200
    assert "nog niet ingesteld" in resp.get_data(as_text=True).lower()


def test_documenten_root_toont_bestanden_en_mappen(app_client, monkeypatch):
    import webapp.app as appmodule

    items = [
        drive_browse.DriveItem(naam="Huidige huurders", pad="Huidige huurders", is_map=True, grootte=None, gewijzigd_op="", mimetype=""),
        drive_browse.DriveItem(naam="contract.pdf", pad="contract.pdf", is_map=False, grootte=123, gewijzigd_op="2026-07-01", mimetype="application/pdf"),
    ]
    monkeypatch.setattr(appmodule.drive_browse, "list_bestanden", lambda config, pand, pad: items)
    resp = app_client.get("/pand/mahoniestraat/documenten")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Huidige huurders" in body
    assert "contract.pdf" in body


def test_documenten_leeg_toont_lege_melding(app_client, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule.drive_browse, "list_bestanden", lambda config, pand, pad: [])
    resp = app_client.get("/pand/mahoniestraat/documenten")
    assert "deze map is leeg" in resp.get_data(as_text=True).lower()


def test_documenten_geneste_map_toont_broodkruimelpad(app_client, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule.drive_browse, "list_bestanden", lambda config, pand, pad: [])
    resp = app_client.get("/pand/mahoniestraat/documenten/Huidige huurders/Jane Doe")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Huidige huurders" in body
    assert "Jane Doe" in body


def test_documenten_lijst_mislukt_toont_foutmelding(app_client, monkeypatch):
    import webapp.app as appmodule

    def _falend(config, pand, pad):
        raise drive_browse.DriveBrowseError("simulated rclone-fout")

    monkeypatch.setattr(appmodule.drive_browse, "list_bestanden", _falend)
    resp = app_client.get("/pand/mahoniestraat/documenten", follow_redirects=True)
    assert resp.status_code == 200
    assert "simulated rclone-fout" in resp.get_data(as_text=True)


def test_documenten_upload_slaat_bestand_op(app_client, monkeypatch):
    import webapp.app as appmodule

    opgevangen = []
    monkeypatch.setattr(
        appmodule.drive_browse, "upload_bestand",
        lambda config, pand, pad, bestandsnaam, inhoud: opgevangen.append((pad, bestandsnaam, inhoud)),
    )
    resp = app_client.post(
        "/pand/mahoniestraat/documenten/upload",
        data={"pad": "Huidige huurders/Jane Doe", "bestand": (__import__("io").BytesIO(b"fake-bytes"), "id.jpg")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "geupload" in resp.get_data(as_text=True).lower()
    assert opgevangen == [("Huidige huurders/Jane Doe", "id.jpg", b"fake-bytes")]


def test_documenten_upload_zonder_rclone_remote_geeft_melding(tmp_path, monkeypatch):
    client = _bouw_app_client(tmp_path, monkeypatch, rclone_remote=None)
    resp = client.post(
        "/pand/mahoniestraat/documenten/upload",
        data={"pad": "", "bestand": (__import__("io").BytesIO(b"x"), "test.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "nog niet ingesteld" in resp.get_data(as_text=True).lower()


def test_documenten_upload_mislukt_toont_foutmelding(app_client, monkeypatch):
    import webapp.app as appmodule

    def _falend(*args, **kwargs):
        raise drive_browse.DriveBrowseError("simulated upload-fout")

    monkeypatch.setattr(appmodule.drive_browse, "upload_bestand", _falend)
    resp = app_client.post(
        "/pand/mahoniestraat/documenten/upload",
        data={"pad": "", "bestand": (__import__("io").BytesIO(b"x"), "test.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "mislukt" in resp.get_data(as_text=True).lower()


def test_documenten_nieuwe_map_aanmaken(app_client, monkeypatch):
    import webapp.app as appmodule

    opgevangen = []
    monkeypatch.setattr(
        appmodule.drive_browse, "maak_map",
        lambda config, pand, pad, naam: opgevangen.append((pad, naam)),
    )
    resp = app_client.post(
        "/pand/mahoniestraat/documenten/nieuwe-map",
        data={"pad": "Huidige huurders", "naam": "Nieuwe map"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "aangemaakt" in resp.get_data(as_text=True).lower()
    assert opgevangen == [("Huidige huurders", "Nieuwe map")]


def test_documenten_download_geeft_inhoud_terug(app_client, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule.drive_browse, "lees_bestand", lambda config, pand, pad: b"pdf-inhoud")
    resp = app_client.get("/pand/mahoniestraat/documenten/bestand/Huidige huurders/contract.pdf")
    assert resp.status_code == 200
    assert resp.data == b"pdf-inhoud"
    assert "contract.pdf" in resp.headers["Content-Disposition"]


def test_documenten_download_onbekend_bestand_geeft_404(app_client, monkeypatch):
    import webapp.app as appmodule

    def _falend(config, pand, pad):
        raise drive_browse.DriveBrowseError("niet gevonden")

    monkeypatch.setattr(appmodule.drive_browse, "lees_bestand", _falend)
    resp = app_client.get("/pand/mahoniestraat/documenten/bestand/onbekend.pdf")
    assert resp.status_code == 404
