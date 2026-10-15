"""Tests voor het activiteits-logboek van testaccounts: elke pagina die een
testaccount opent wordt geteld, en alleen de hoofdgebruiker (jmmreckman) ziet de
knop + pagina met dat logboek onder Totaal overzicht."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner import state
from kamerverhuur_scanner.config import Config
from webapp.app import create_app


class _FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return []


@pytest.fixture
def opzet(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", _FakeSheetClient)

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "bunq_rekening_iban": "NL81BUNQ2163127125"},
    ]))
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "jmmreckman": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
        "justin": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
        "kijker": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": [],
                   "test_account": True},
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
    return app.test_client(), config


def _login(client, username):
    return client.post("/login", data={"username": username, "password": "geheim123"}, follow_redirects=False)


def test_paginaweergave_van_testaccount_wordt_gelogd(opzet):
    client, config = opzet
    _login(client, "kijker")
    client.get("/winst-overzicht")
    client.get("/pand/mahoniestraat/")
    regels = state.laad_testaccount_logboek(config.state_dir)
    assert len(regels) >= 2
    assert all(r["gebruiker"] == "kijker" for r in regels)
    paden = {r["pad"] for r in regels}
    assert "/winst-overzicht" in paden
    assert "/pand/mahoniestraat/" in paden


def test_activiteit_van_gewone_gebruiker_wordt_niet_gelogd(opzet):
    client, config = opzet
    _login(client, "justin")
    client.get("/winst-overzicht")
    client.get("/pand/mahoniestraat/")
    assert state.laad_testaccount_logboek(config.state_dir) == []


def test_alleen_hoofdgebruiker_ziet_de_knop(opzet):
    client, _config = opzet
    _login(client, "jmmreckman")
    assert "Logboek test accounts" in client.get("/winst-overzicht").get_data(as_text=True)


def test_gewone_gebruiker_ziet_de_knop_niet(opzet):
    client, _config = opzet
    _login(client, "justin")
    assert "Logboek test accounts" not in client.get("/winst-overzicht").get_data(as_text=True)


def test_logboekpagina_is_verboden_voor_niet_hoofdgebruiker(opzet):
    client, _config = opzet
    _login(client, "justin")
    assert client.get("/winst-overzicht/test-logboek").status_code == 403


def test_hoofdgebruiker_ziet_activiteit_van_testaccount(opzet):
    client, _config = opzet
    _login(client, "kijker")
    client.get("/winst-overzicht")
    client.get("/pand/mahoniestraat/")
    client.get("/logout")
    _login(client, "jmmreckman")

    body = client.get("/winst-overzicht/test-logboek").get_data(as_text=True)
    assert "kijker" in body
    assert "/pand/mahoniestraat/" in body  # laat zien wélke pagina's zijn bekeken
    assert "Actieve tijd" in body
