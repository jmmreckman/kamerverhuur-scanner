"""Integratietest voor het bewerkbare huurders-grid (/pand/<slug>/huurders/grid).
Draait tegen de ECHTE DbClient (SQLite in tmp_path) - geen nep-sheet, want het
grid is juist de nieuwe, database-gestuurde bewerkweg. Vereist webapp.app, dus
draait in CI (niet in de kale sandbox zonder bunq_sdk/xhtml2pdf)."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner import db
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.db_client import DbClient
from kamerverhuur_scanner.models import Pand
from webapp.app import create_app


def _pand() -> Pand:
    return Pand(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        bunq_rekening_iban="NL81BUNQ2163127125",
    )


@pytest.fixture
def ctx(tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "beheerder": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
    }))
    props = tmp_path / "properties.json"
    props.write_text("[]")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = Config(
        google_service_account_file="fake.json", properties_file=str(props),
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file=str(users_file), flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, state_dir=str(state_dir),
    )
    db.zet_pand(config, "mahoniestraat", {
        "naam": "Mahoniestraat 15", "google_sheet_id": "", "bunq_rekening_iban": "NL81BUNQ2163127125",
    })
    app = create_app(config)
    app.testing = True
    return app.test_client(), config


def _login(c):
    c.post("/login", data={"username": "beheerder", "password": "geheim123"})


def test_grid_toont_pagina(ctx):
    c, config = ctx
    DbClient(config, _pand()).voeg_kamer_toe("Kamer 1", "Jan")
    _login(c)
    resp = c.get("/pand/mahoniestraat/huurders/grid")
    assert resp.status_code == 200
    assert b"Kamer 1" in resp.data


def test_grid_voegt_rij_toe(ctx):
    c, config = ctx
    _login(c)
    resp = c.post("/pand/mahoniestraat/huurders/grid", data={
        "rij_indices": "new0",
        "r_new0_kamer": "Kamer 1", "r_new0_naam": "Jan",
        "r_new0_verwacht_bedrag": "550,00", "r_new0_iban": "nl81 bunq 2163 1271 25",
    }, follow_redirects=True)
    assert resp.status_code == 200
    kamers = DbClient(config, _pand()).get_kamers()
    assert [(k.kamer, k.naam) for k in kamers] == [("Kamer 1", "Jan")]
    assert kamers[0].verwacht_bedrag == Decimal("550.00")
    assert kamers[0].iban == "NL81BUNQ2163127125"  # genormaliseerd (hoofdletters, geen spaties)


def test_grid_bewerkt_bestaande_rij_en_behoudt_diepe_velden(ctx):
    c, config = ctx
    client = DbClient(config, _pand())
    rid = client.voeg_kamer_toe("Kamer 1", "Jan")
    # Zet een diep contractveld dat NIET in het grid staat; dat moet bewaard blijven.
    client.update_kamer(row_index=rid, naam="Jan", kamer="Kamer 1",
                        verwacht_bedrag=Decimal("500"), iban=None, zoekwoord=None,
                        studentnummer="s123456")
    _login(c)
    c.post("/pand/mahoniestraat/huurders/grid", data={
        "rij_indices": str(rid),
        f"r_{rid}_id": str(rid), f"r_{rid}_kamer": "Kamer 1",
        f"r_{rid}_naam": "Jan de Vries", f"r_{rid}_verwacht_bedrag": "600",
    }, follow_redirects=True)
    k = DbClient(config, _pand()).get_kamers()[0]
    assert k.naam == "Jan de Vries"
    assert k.verwacht_bedrag == Decimal("600.00")
    assert k.studentnummer == "s123456"  # diep veld bewaard


def test_grid_verwijdert_rij(ctx):
    c, config = ctx
    client = DbClient(config, _pand())
    rid1 = client.voeg_kamer_toe("Kamer 1", "Jan")
    rid2 = client.voeg_kamer_toe("Kamer 2", "Piet")
    _login(c)
    c.post("/pand/mahoniestraat/huurders/grid", data={
        "rij_indices": f"{rid1},{rid2}",
        f"r_{rid1}_id": str(rid1), f"r_{rid1}_kamer": "Kamer 1", f"r_{rid1}_naam": "Jan",
        f"r_{rid1}_verwacht_bedrag": "500",
        f"r_{rid2}_id": str(rid2), f"r_{rid2}_kamer": "Kamer 2", f"r_{rid2}_verwijder": "on",
    }, follow_redirects=True)
    kamers = DbClient(config, _pand()).get_kamers()
    assert [k.kamer for k in kamers] == ["Kamer 1"]
