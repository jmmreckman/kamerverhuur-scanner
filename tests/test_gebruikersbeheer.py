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


# --- Testaccounts ----------------------------------------------------------

def _maak_testaccount(users_file, username="kijker", alle_panden=True):
    users = json.loads(users_file.read_text())
    users[username] = {
        "wachtwoord_hash": generate_password_hash("geheim123"),
        "alle_panden": alle_panden, "panden": [] if alle_panden else ["mahoniestraat"],
        "test_account": True,
    }
    users_file.write_text(json.dumps(users))


def test_gebruiker_aanmaken_als_testaccount_slaat_vlag_op(client):
    c, users_file = client
    _login(c, "beheerder")
    c.post("/beheer/gebruikers/nieuw", data={
        "username": "kijker", "wachtwoord": "geheim123", "alle_panden": "on", "test_account": "on",
    })
    assert json.loads(users_file.read_text())["kijker"]["test_account"] is True


def test_gebruiker_zonder_vinkje_is_geen_testaccount(client):
    c, users_file = client
    _login(c, "beheerder")
    c.post("/beheer/gebruikers/nieuw", data={
        "username": "echt", "wachtwoord": "geheim123", "alle_panden": "on",
    })
    assert json.loads(users_file.read_text())["echt"]["test_account"] is False


def test_bewerken_behoudt_email_en_mailvoorkeuren(client):
    # zet_gebruiker mag bij het bewerken van de toegang de e-mail/mailvoorkeuren
    # niet wissen (die stelt de gebruiker zelf in bij Mailvoorkeuren).
    c, users_file = client
    users = json.loads(users_file.read_text())
    users["justin"]["email"] = "justin@example.com"
    users["justin"]["mail_voorkeuren"] = {"huishouden": False}
    users_file.write_text(json.dumps(users))
    _login(c, "beheerder")
    c.post("/beheer/gebruikers/justin/bewerken", data={"wachtwoord": "", "alle_panden": "on"})
    opgeslagen = json.loads(users_file.read_text())["justin"]
    assert opgeslagen["email"] == "justin@example.com"
    assert opgeslagen["mail_voorkeuren"] == {"huishouden": False}


def test_testaccount_ziet_waarschuwingsbanner(client):
    c, users_file = client
    _maak_testaccount(users_file)
    _login(c, "kijker")
    resp = c.get("/beheer/gebruikers")
    assert "testaccount" in resp.get_data(as_text=True).lower()


def test_testaccount_wordt_geblokkeerd_bij_echte_actie(client):
    c, users_file = client
    _maak_testaccount(users_file)
    _login(c, "kijker")
    resp = c.post("/beheer/gebruikers/justin/verwijderen", follow_redirects=True)
    assert "testaccount" in resp.get_data(as_text=True).lower()
    # De verwijdering is niet echt uitgevoerd.
    assert "justin" in json.loads(users_file.read_text())


def test_testaccount_mag_wel_eigen_mailvoorkeuren_opslaan(client):
    c, users_file = client
    _maak_testaccount(users_file)
    _login(c, "kijker")
    c.post("/account/mail-voorkeuren", data={"email": "kijker@example.com"}, follow_redirects=True)
    opgeslagen = json.loads(users_file.read_text())["kijker"]
    assert opgeslagen["email"] == "kijker@example.com"
    assert opgeslagen["test_account"] is True  # blijft een testaccount


def test_echte_beheerder_wordt_niet_geblokkeerd(client):
    c, users_file = client  # beheerder is géén testaccount
    _login(c, "beheerder")
    resp = c.post("/beheer/gebruikers/justin/verwijderen", follow_redirects=True)
    assert "testaccount" not in resp.get_data(as_text=True).lower()
    assert "justin" not in json.loads(users_file.read_text())
