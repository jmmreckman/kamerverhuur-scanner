"""Tests voor de winstberekeningspagina (per pand), de gecombineerde
"totale winst alle panden"-pagina, en de dashboard-/pandkiezertegel."""
import json
from datetime import date
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner import state
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Payment, Tenant
from webapp.app import create_app


class FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return [Tenant(row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"))]


class FakeBunqClient:
    def __init__(self, _config):
        pass

    def get_outgoing_payments(self, pand, since):
        return [
            Payment(bedrag=Decimal("100.00"), valuta="EUR", tegenpartij_naam="Energieleverancier",
                    tegenpartij_iban="NL91ABNA0417164300", omschrijving="Energie", datum=date(2026, 5, 3)),
            Payment(bedrag=Decimal("100.00"), valuta="EUR", tegenpartij_naam="Energieleverancier",
                    tegenpartij_iban="NL91ABNA0417164300", omschrijving="Energie", datum=date(2026, 6, 3)),
        ]


@pytest.fixture
def opzet(tmp_path, monkeypatch):
    import webapp.app as appmodule
    import kamerverhuur_scanner.runner as runner_module
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(runner_module, "BunqClient", FakeBunqClient)

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "bunq_rekening_iban": "NL81BUNQ2163127125", "onderhoud_reserve_per_maand": "60.00"},
        {"slug": "baumannlaan", "naam": "Burgemeester Baumannlaan 70b", "google_sheet_id": "fake2",
         "bunq_rekening_iban": "NL00OTHER0000000000"},
    ]))
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "beheerder": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
        "justin": {
            "wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": False,
            "panden": ["mahoniestraat"],
        },
    }))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = Config(
        google_service_account_file="fake.json", properties_file=str(properties_file),
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file=str(users_file), flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, state_dir=str(state_dir),
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client, config


def test_winstberekening_toont_inkomsten_lasten_en_winst(opzet):
    client, config = opzet
    resultaat = {"resultaten": [{"kamer": "1", "naam": "Jan", "verwacht_bedrag": "650.00",
                                  "ontvangen_bedrag": "650.00", "status": "Betaald"}],
                 "niet_gekoppelde_betalingen": 0, "gecontroleerd_op": "01-07-2026 10:00"}
    (state._bestandsnaam("mahoniestraat", config.state_dir)).write_text(json.dumps(resultaat))

    resp = client.get("/pand/mahoniestraat/winst")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Energieleverancier" in body
    # 650 inkomsten - 100 (last) - 75 (belasting) - 60 (onderhoud) = 415 winst
    assert "415,00" in body
    assert "60,00" in body  # onderhoudsreserve
    assert "75,00" in body  # belasting


def test_winstberekening_legt_snapshot_vast(opzet):
    client, config = opzet
    assert state.laad_winst_geschiedenis("mahoniestraat", config.state_dir) == []
    client.get("/pand/mahoniestraat/winst")
    geschiedenis = state.laad_winst_geschiedenis("mahoniestraat", config.state_dir)
    assert len(geschiedenis) == 1


def test_dashboard_toont_bereken_zonder_snapshot(opzet):
    client, _config = opzet
    resp = client.get("/pand/mahoniestraat/")
    assert "Bereken" in resp.get_data(as_text=True)


def test_dashboard_toont_laatste_winst_na_bezoek_winstpagina(opzet):
    client, _config = opzet
    client.get("/pand/mahoniestraat/winst")  # legt een snapshot vast
    resp = client.get("/pand/mahoniestraat/")
    body = resp.get_data(as_text=True)
    assert "winstberekening" in body.lower()
    assert "Bereken" not in body


def test_winst_overzicht_combineert_meerdere_panden(opzet):
    client, config = opzet
    state.voeg_winst_snapshot_toe("mahoniestraat", Decimal("1000.00"), config.state_dir)
    state.voeg_winst_snapshot_toe("baumannlaan", Decimal("500.00"), config.state_dir)

    resp = client.get("/winst-overzicht")
    assert resp.status_code == 200


def test_pandkiezer_toont_totale_winst_alle_panden(opzet):
    client, config = opzet
    # baumannlaan heeft in deze fixture maar 1 beheerder ("beheerder" zelf,
    # via alle_panden) - justin heeft alleen toegang tot mahoniestraat.
    state.voeg_winst_snapshot_toe("baumannlaan", Decimal("500.00"), config.state_dir)

    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert "totale winst alle panden" in body.lower()
    assert "500,00" in body


def test_pandkiezer_verdeelt_winst_bij_meerdere_beheerders(opzet):
    client, config = opzet
    state.voeg_winst_snapshot_toe("mahoniestraat", Decimal("1000.00"), config.state_dir)
    # justin heeft ook toegang tot mahoniestraat, dus de winst van dat pand
    # moet hier door 2 gedeeld worden (500,00) - baumannlaan blijft onverdeeld.
    state.voeg_winst_snapshot_toe("baumannlaan", Decimal("500.00"), config.state_dir)

    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert "1.000,00" in body  # 500 (mahoniestraat, verdeeld) + 500 (baumannlaan, onverdeeld)
