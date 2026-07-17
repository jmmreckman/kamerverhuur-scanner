"""Tests voor het archiveren van vertrokken huurders: blijven nog even
(grijs, tot 1 maand na hun contract-einddatum) zichtbaar op de
Huurders-pagina zodra een kamer een andere huurder krijgt."""
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import HistorieRegel, Status, Tenant, VertrokkenHuurder
from webapp.app import create_app

KAMER_1 = Tenant(
    row_index=2, naam="Bence Neumayer", kamer="1", verwacht_bedrag=Decimal("919.00"),
    email="bence@example.com", telefoonnummer="0612345678", contract_einddatum="01-07-2026",
)


class FakeSheetClient:
    laatste_update = None
    archiveer_aangeroepen_met = None
    vertrokken_huurders = []
    alle_vertrokken_huurders = []
    geschiedenis_per_kamer = {}

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
        return FakeSheetClient.vertrokken_huurders

    def get_alle_vertrokken_huurders(self):
        return FakeSheetClient.alle_vertrokken_huurders

    def get_vertrokken_huurder(self, row_index):
        return next((v for v in FakeSheetClient.alle_vertrokken_huurders if v.row_index == row_index), None)

    def get_geschiedenis(self, kamer):
        return FakeSheetClient.geschiedenis_per_kamer.get(kamer, [])


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    FakeSheetClient.laatste_update = None
    FakeSheetClient.archiveer_aangeroepen_met = None
    FakeSheetClient.vertrokken_huurders = []
    FakeSheetClient.alle_vertrokken_huurders = []
    FakeSheetClient.geschiedenis_per_kamer = {}

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
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, state_dir=str(tmp_path),
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client


def test_huurder_bewerken_naar_andere_naam_archiveert_de_vertrekkende(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/huurders/1/bewerken",
        data={"kamer": "1", "naam": "Nieuwe Huurder", "verwacht_bedrag": "919,00"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    gearchiveerd = FakeSheetClient.archiveer_aangeroepen_met
    assert gearchiveerd is not None
    assert gearchiveerd.naam == "Bence Neumayer"


def test_huurder_bewerken_zelfde_naam_archiveert_niet(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/huurders/1/bewerken",
        data={"kamer": "1", "naam": "Bence Neumayer", "verwacht_bedrag": "925,00"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert FakeSheetClient.archiveer_aangeroepen_met is None


def test_huurder_bewerken_kamer_leegmaken_archiveert(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/huurders/1/bewerken",
        data={"kamer": "1", "naam": "", "verwacht_bedrag": "919,00"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    gearchiveerd = FakeSheetClient.archiveer_aangeroepen_met
    assert gearchiveerd is not None
    assert gearchiveerd.naam == "Bence Neumayer"


def test_huurders_pagina_toont_vertrokken_huurder_grijs_gemarkeerd(app_client):
    FakeSheetClient.vertrokken_huurders = [
        VertrokkenHuurder(
            kamer="1", naam="Oud-Huurder", email="oud@example.com", telefoonnummer="0698765432",
            contract_einddatum="01-07-2026", vertrokken_op=date.today() - timedelta(days=3),
        )
    ]
    resp = app_client.get("/pand/mahoniestraat/huurders")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Oud-Huurder" in body
    assert "voormalig" in body.lower()
    assert "oud@example.com" in body


def test_huurders_pagina_zonder_vertrokken_huurders_toont_geen_sectie(app_client):
    resp = app_client.get("/pand/mahoniestraat/huurders")
    assert resp.status_code == 200
    assert "Voormalige huurders" not in resp.get_data(as_text=True)


def test_huurders_pagina_heeft_knop_naar_oude_huurders(app_client):
    resp = app_client.get("/pand/mahoniestraat/huurders")
    assert resp.status_code == 200
    assert 'href="/pand/mahoniestraat/huurders/oud"' in resp.get_data(as_text=True)


# --- Oude huurders (permanent archief) ---


def test_oude_huurders_pagina_toont_ook_langer_vertrokken_huurders(app_client):
    # deze zou NIET meer in get_recent_vertrokken_huurders() zitten (buiten de
    # 31-dagen-termijn), maar moet wel permanent op deze pagina blijven staan.
    FakeSheetClient.alle_vertrokken_huurders = [
        VertrokkenHuurder(
            kamer="1", naam="Allang Vertrokken", email="oud@example.com", telefoonnummer=None,
            contract_einddatum="01-01-2025", vertrokken_op=date(2025, 1, 1), row_index=2,
        )
    ]
    resp = app_client.get("/pand/mahoniestraat/huurders/oud")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Allang Vertrokken" in body
    assert "oud@example.com" in body


def test_oude_huurders_pagina_zonder_huurders_toont_nette_melding(app_client):
    resp = app_client.get("/pand/mahoniestraat/huurders/oud")
    assert resp.status_code == 200
    assert "Nog geen oude huurders" in resp.get_data(as_text=True)


def test_oude_huurder_detail_toont_gegevens_en_alleen_eigen_betaalgeschiedenis(app_client):
    FakeSheetClient.alle_vertrokken_huurders = [
        VertrokkenHuurder(
            kamer="1", naam="Matias", email="matias@example.com", telefoonnummer="0611111111",
            contract_einddatum="31-07-2026", vertrokken_op=date(2026, 7, 15), row_index=2,
        )
    ]
    FakeSheetClient.geschiedenis_per_kamer = {
        "1": [
            HistorieRegel(
                maand="2026-06", kamer="1", huurder="Matias", verwacht_bedrag=Decimal("870.00"),
                ontvangen_bedrag=Decimal("870.00"), status=Status.BETAALD,
            ),
            # augustus is al de nieuwe huurder - hoort dus niet bij Matias' geschiedenis
            HistorieRegel(
                maand="2026-08", kamer="1", huurder="Thomas", verwacht_bedrag=Decimal("870.00"),
                ontvangen_bedrag=Decimal("0.00"), status=Status.NIET_ONTVANGEN,
            ),
        ]
    }
    resp = app_client.get("/pand/mahoniestraat/huurders/oud/2")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Matias" in body
    assert "matias@example.com" in body
    assert "juni" in body.lower()
    assert "Thomas" not in body


def test_oude_huurder_detail_onbekende_row_index_geeft_404(app_client):
    resp = app_client.get("/pand/mahoniestraat/huurders/oud/999")
    assert resp.status_code == 404
