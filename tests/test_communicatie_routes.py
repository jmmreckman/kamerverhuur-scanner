"""Integratietests voor de Communicatie-pagina per huurder: tijdlijn, profiel,
handmatig toevoegen, mail versturen (+loggen), en het AI-sparpaneel - met een
nep-Sheetclient en een nep-AI-client, nooit de echte Google/Anthropic API's."""
import dataclasses
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.ai_client import AIError
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.mailer import MailError
from kamerverhuur_scanner.models import Pand, Tenant
from webapp.app import create_app

KAMER = Tenant(
    row_index=2, naam="Jane Doe", kamer="1", verwacht_bedrag=Decimal("650.00"),
    email="jane@example.com", communicatie_profiel="Emotionele huurder, kort en zakelijk blijven.",
)


class FakeSheetClient:
    def __init__(self, _config, pand):
        self.pand = pand
        self.communicatie = []
        self.laatste_profiel = None

    def get_kamers(self):
        kamer = KAMER
        if self.laatste_profiel is not None:
            kamer = dataclasses.replace(kamer, communicatie_profiel=self.laatste_profiel)
        return [kamer]

    def update_communicatie_profiel(self, row_index, profiel):
        self.laatste_profiel = profiel

    laat_communicatie_falen = False

    def add_communicatie(self, kamer, huurder_naam, richting, onderwerp, tekst):
        if self.laat_communicatie_falen:
            raise RuntimeError("simuleert een mislukte Google Sheets-schrijfactie")
        self.communicatie.append(
            {"kamer": kamer, "huurder": huurder_naam, "richting": richting, "onderwerp": onderwerp, "tekst": tekst}
        )

    def get_communicatie(self, kamer):
        return [
            ["10-07-2026 12:00", c["kamer"], c["huurder"], c["richting"], c["onderwerp"], c["tekst"]]
            for c in self.communicatie if c["kamer"] == kamer
        ]


_fake_sheet_singleton = {}


def _fake_sheet_factory(config, pand):
    if pand.slug not in _fake_sheet_singleton:
        _fake_sheet_singleton[pand.slug] = FakeSheetClient(config, pand)
    return _fake_sheet_singleton[pand.slug]


def _bouw_app_client(tmp_path, monkeypatch, config_overrides=None):
    import webapp.app as appmodule
    _fake_sheet_singleton.clear()
    monkeypatch.setattr(appmodule, "SheetClient", _fake_sheet_factory)

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "bunq_rekening_iban": "NL81BUNQ2163127125", "extra_bcc": ["justin@example.com"]},
    ]))
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "beheerder": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
    }))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_velden = dict(
        google_service_account_file="fake.json", properties_file=str(properties_file),
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file=str(users_file), flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, state_dir=str(state_dir),
        smtp_host="smtp.example.com", smtp_port=587, smtp_username="info@steenhub.nl",
        smtp_password="geheim", smtp_from_email="info@steenhub.nl", smtp_from_naam="Steenhub",
        email_bcc=["jurian@example.com", "justin@example.com"],
        anthropic_api_key="sk-ant-test",
    )
    config_velden.update(config_overrides or {})
    config = Config(**config_velden)
    pand = Pand(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="fake",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        google_drive_folder_id=None, bunq_rekening_iban="NL81BUNQ2163127125", extra_bcc=["justin@example.com"],
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    return _bouw_app_client(tmp_path, monkeypatch)


@pytest.fixture
def verstuurde_mails(monkeypatch):
    verstuurd = []

    def _fake_verstuur_email(config, aan, onderwerp, tekst, bcc=None, **kwargs):
        verstuurd.append({"aan": aan, "onderwerp": onderwerp, "tekst": tekst, "bcc": bcc})

    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "verstuur_email", _fake_verstuur_email)
    return verstuurd


@pytest.fixture
def fake_ai(monkeypatch):
    """Monkeypatcht genereer_reactie zodat de echte Anthropic API nooit wordt aangeroepen."""
    aanroepen = []

    def _fake_genereer_reactie(config, profiel, geschiedenis, chatgeschiedenis):
        aanroepen.append({"profiel": profiel, "geschiedenis": geschiedenis, "chatgeschiedenis": chatgeschiedenis})
        return "Bedankt voor uw bericht - we sturen deze week een monteur langs."

    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "genereer_reactie", _fake_genereer_reactie)
    return aanroepen


# --- Overzicht + profiel ---


def test_communicatie_overzicht_vereist_login(tmp_path, monkeypatch):
    client = _bouw_app_client(tmp_path, monkeypatch)
    client.get("/logout")
    resp = client.get("/pand/mahoniestraat/kamers/1/communicatie", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_communicatie_overzicht_toont_profiel_en_lijst(app_client):
    app_client.get("/pand/mahoniestraat/kamers/1/communicatie")  # instantieert de FakeSheetClient-singleton
    sheet = _fake_sheet_singleton["mahoniestraat"]
    sheet.add_communicatie("1", "Jane Doe", "Inkomend", "Verwarming", "De verwarming doet het niet.")
    resp = app_client.get("/pand/mahoniestraat/kamers/1/communicatie")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Emotionele huurder, kort en zakelijk blijven." in body
    assert "De verwarming doet het niet." in body


def test_communicatie_profiel_opslaan(app_client):
    app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/profiel", data={"profiel": "Nieuw profiel."},
        follow_redirects=True,
    )
    assert _fake_sheet_singleton["mahoniestraat"].laatste_profiel == "Nieuw profiel."


def test_communicatie_toevoegen_handmatig(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/toevoegen",
        data={"richting": "Inkomend", "onderwerp": "Oude klacht", "tekst": "Dit is een oude, teruggeplakte mail."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Dit is een oude, teruggeplakte mail." in resp.get_data(as_text=True)
    assert len(_fake_sheet_singleton["mahoniestraat"].communicatie) == 1


def test_communicatie_toevoegen_zonder_tekst_geeft_melding(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/toevoegen",
        data={"richting": "Inkomend", "tekst": ""}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "vul de richting en tekst" in resp.get_data(as_text=True).lower()
    assert _fake_sheet_singleton["mahoniestraat"].communicatie == []


# --- AI-sparren ---


def test_sparren_start_stuurt_profiel_en_geschiedenis_mee(app_client, fake_ai):
    app_client.get("/pand/mahoniestraat/kamers/1/communicatie")  # instantieert de FakeSheetClient-singleton
    sheet = _fake_sheet_singleton["mahoniestraat"]
    sheet.add_communicatie("1", "Jane Doe", "Inkomend", "Eerder", "Eerdere klacht over de lift.")

    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/sparren",
        data={"chatgeschiedenis_json": "[]", "nieuw_bericht": "De verwarming doet het al een week niet meer!"},
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Bedankt voor uw bericht" in body

    assert len(fake_ai) == 1
    aanroep = fake_ai[0]
    assert aanroep["profiel"] == "Emotionele huurder, kort en zakelijk blijven."
    assert "Eerdere klacht over de lift." in aanroep["geschiedenis"]
    assert aanroep["chatgeschiedenis"] == [
        {"role": "user", "content": "De verwarming doet het al een week niet meer!"}
    ]


def test_sparren_vervolgbericht_stuurt_volledige_chatgeschiedenis_mee(app_client, fake_ai):
    eerste_chat = json.dumps([
        {"role": "user", "content": "De verwarming doet het niet."},
        {"role": "assistant", "content": "Bedankt voor uw bericht - we sturen deze week een monteur langs."},
    ])
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/sparren",
        data={"chatgeschiedenis_json": eerste_chat, "nieuw_bericht": "Maak het iets korter."},
    )
    assert resp.status_code == 200
    assert len(fake_ai) == 1
    assert len(fake_ai[0]["chatgeschiedenis"]) == 3
    assert fake_ai[0]["chatgeschiedenis"][-1] == {"role": "user", "content": "Maak het iets korter."}


def test_sparren_zonder_bericht_geeft_melding(app_client, fake_ai):
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/sparren",
        data={"chatgeschiedenis_json": "[]", "nieuw_bericht": ""},
    )
    assert resp.status_code == 200
    assert "typ eerst een bericht" in resp.get_data(as_text=True).lower()
    assert fake_ai == []


def test_sparren_mislukte_ai_aanvraag_geeft_foutmelding_niet_500(app_client, monkeypatch):
    def _falende_ai(config, profiel, geschiedenis, chatgeschiedenis):
        raise AIError("AI-sparren is nog niet ingesteld - vul ANTHROPIC_API_KEY in .env in.")

    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "genereer_reactie", _falende_ai)

    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/sparren",
        data={"chatgeschiedenis_json": "[]", "nieuw_bericht": "De verwarming doet het niet."},
    )
    assert resp.status_code == 200
    assert "anthropic_api_key" in resp.get_data(as_text=True).lower()


def test_sparren_met_ongeldige_chatgeschiedenis_redirect(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/sparren",
        data={"chatgeschiedenis_json": "dit is geen json", "nieuw_bericht": "hoi"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "ongeldige chatgeschiedenis" in resp.get_data(as_text=True).lower()


# --- Concept gebruiken + versturen ---


def test_opstellen_toont_voorstel_met_concepttekst(app_client):
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/opstellen",
        data={"tekst": "We sturen deze week een monteur langs."},
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "We sturen deze week een monteur langs." in body
    assert 'value="jane@example.com"' in body


def test_versturen_stuurt_mail_en_logt_in_communicatielijst(app_client, verstuurde_mails):
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/versturen",
        data={"aan": "jane@example.com", "onderwerp": "Re: Verwarming", "tekst": "We sturen een monteur langs."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "toegevoegd aan de communicatielijst" in resp.get_data(as_text=True).lower()

    assert len(verstuurde_mails) == 1
    mail = verstuurde_mails[0]
    assert mail["aan"] == "jane@example.com"
    assert mail["onderwerp"] == "Re: Verwarming"
    assert set(mail["bcc"]) == {"jurian@example.com", "justin@example.com"}  # alle beheerders, niet alleen 1

    sheet = _fake_sheet_singleton["mahoniestraat"]
    assert len(sheet.communicatie) == 1
    entry = sheet.communicatie[0]
    assert entry["richting"] == "Uitgaand"
    assert entry["tekst"] == "We sturen een monteur langs."


def test_versturen_zonder_velden_geeft_melding(app_client, verstuurde_mails):
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/versturen",
        data={"aan": "", "onderwerp": "", "tekst": ""},
    )
    assert resp.status_code == 200
    assert "vul een ontvanger" in resp.get_data(as_text=True).lower()
    assert verstuurde_mails == []


def test_versturen_mislukte_mail_wordt_niet_gelogd(app_client, monkeypatch):
    def _falende_mailer(config, aan, onderwerp, tekst, bcc=None, **kwargs):
        raise MailError("SMTP tijdelijk niet bereikbaar")

    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "verstuur_email", _falende_mailer)

    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/versturen",
        data={"aan": "jane@example.com", "onderwerp": "Re: Verwarming", "tekst": "We sturen een monteur langs."},
    )
    assert resp.status_code == 200
    assert "smtp" in resp.get_data(as_text=True).lower()
    assert _fake_sheet_singleton["mahoniestraat"].communicatie == []


def test_versturen_mislukte_sheet_schrijfactie_meldt_maar_crasht_niet(app_client, verstuurde_mails):
    app_client.get("/pand/mahoniestraat/kamers/1/communicatie")  # instantieert de FakeSheetClient-singleton
    _fake_sheet_singleton["mahoniestraat"].laat_communicatie_falen = True
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/communicatie/versturen",
        data={"aan": "jane@example.com", "onderwerp": "Re: Verwarming", "tekst": "We sturen een monteur langs."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert len(verstuurde_mails) == 1  # de mail is dus wel echt verstuurd
    assert "kon niet automatisch" in resp.get_data(as_text=True).lower()
