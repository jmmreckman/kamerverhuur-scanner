"""Integratietests voor de gebruikersbeheer-pagina's (/beheer/gebruikers/...)."""
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from webapp.app import create_app


class _FakeSheetClient:
    """Vervangt de echte Google Sheets-koppeling: de dashboard-route (waar
    /login en /start naartoe redirecten) roept deze aan voor de
    aanzeg-waarschuwingen, en heeft in deze tests geen echte sheet nodig."""

    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return []


@pytest.fixture
def client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", _FakeSheetClient)

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "bunq_rekening_iban": "NL81BUNQ2163127125"},
    ]))

    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "beheerder": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
        "justin": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": False, "panden": ["mahoniestraat"]},
    }))

    config = Config(
        google_service_account_file="fake.json",
        properties_file=str(properties_file),
        bunq_conf_file="fake.conf",
        bunq_environment="PRODUCTION",
        bunq_api_key=None,
        users_file=str(users_file),
        flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"),
        vooruitbetaling_dagen=14,
    )
    app = create_app(config)
    app.testing = True
    return app.test_client(), users_file


def _login(client, username, password="geheim123"):
    # follow_redirects=False: na login redirect je normaal naar het dashboard van
    # het pand (dat hier geen echte Google/bunq-koppeling heeft) - voor deze
    # tests hebben we alleen de ingelogde sessie nodig, niet die pagina.
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


def test_niet_beheerder_kan_niet_bij_gebruikersbeheer(client):
    c, _ = client
    _login(c, "justin")
    resp = c.get("/beheer/gebruikers", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Je hebt geen toegang tot gebruikersbeheer" in resp.data


def test_beheerder_ziet_gebruikersoverzicht(client):
    c, _ = client
    _login(c, "beheerder")
    resp = c.get("/beheer/gebruikers")
    assert resp.status_code == 200
    assert b"beheerder" in resp.data and b"justin" in resp.data


def test_beheerder_kan_nieuwe_gebruiker_aanmaken(client):
    c, users_file = client
    _login(c, "beheerder")
    resp = c.post("/beheer/gebruikers/nieuw", data={
        "username": "nieuwegebruiker", "wachtwoord": "geheim123", "panden": ["mahoniestraat"],
    }, follow_redirects=True)
    assert resp.status_code == 200
    users = json.loads(users_file.read_text())
    assert "nieuwegebruiker" in users
    assert users["nieuwegebruiker"]["alle_panden"] is False
    assert users["nieuwegebruiker"]["panden"] == ["mahoniestraat"]


def test_beheerder_kan_toegang_van_ander_wijzigen(client):
    c, users_file = client
    _login(c, "beheerder")
    resp = c.post("/beheer/gebruikers/justin/bewerken", data={"wachtwoord": "", "alle_panden": "on"}, follow_redirects=True)
    assert resp.status_code == 200
    users = json.loads(users_file.read_text())
    assert users["justin"]["alle_panden"] is True


def test_beheerder_kan_zichzelf_niet_beheerrechten_ontnemen(client):
    c, users_file = client
    _login(c, "beheerder")
    resp = c.post("/beheer/gebruikers/beheerder/bewerken", data={"wachtwoord": ""}, follow_redirects=True)
    assert b"Je kunt jezelf niet de toegang tot alle panden ontnemen" in resp.data
    users = json.loads(users_file.read_text())
    assert users["beheerder"]["alle_panden"] is True


def test_beheerder_kan_zichzelf_niet_verwijderen(client):
    c, users_file = client
    _login(c, "beheerder")
    resp = c.post("/beheer/gebruikers/beheerder/verwijderen", follow_redirects=True)
    assert b"Je kunt jezelf niet verwijderen" in resp.data
    users = json.loads(users_file.read_text())
    assert "beheerder" in users


def test_beheerder_kan_andere_gebruiker_verwijderen(client):
    c, users_file = client
    _login(c, "beheerder")
    resp = c.post("/beheer/gebruikers/justin/verwijderen", follow_redirects=True)
    assert resp.status_code == 200
    users = json.loads(users_file.read_text())
    assert "justin" not in users
