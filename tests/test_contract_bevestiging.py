"""Tests voor de "Mail bevestiging"-knop op de Contracten-pagina: verschijnt
pas zodra een contract volledig ondertekend is (herkenbaar aan de definitieve,
"-getekend" bestandsnaam) ÉN de betaling (incl. borg) van de kamer binnen is,
en toont eerst een aanpasbaar voorbeeldscherm - voor panden met een Bold-slot
moet daar eerst verplicht de persoonlijke uitnodigingslink ingevuld worden.

Belangrijke regressie: de knop moet ook nog werken als het concept-contract
(en daarmee zijn eigen metadata) na het tekenen is verwijderd via
"Verwijderen" - alleen de definitieve "-getekend" versie is dan nog over."""
import json
import re
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner import state
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Status, Tenant, TenantResult
from webapp import contracts, ondertekenen
from webapp.app import create_app

TEST_HANDTEKENING_DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

KAMER_1 = Tenant(row_index=2, naam="Bence Neumayer", kamer="1", verwacht_bedrag=Decimal("870.00"))


class FakeSheetClient:
    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return [KAMER_1]

    def get_tenants(self):
        return [KAMER_1]

    def update_kamer(self, **kwargs):
        pass

    def archiveer_vertrokken_huurder(self, kamer):
        pass

    def get_recent_vertrokken_huurders(self):
        return []


def _maak_app_client(tmp_path, monkeypatch, pand_overrides=None):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    monkeypatch.chdir(tmp_path)

    pand = {
        "slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
        "google_drive_folder_id": None, "bunq_rekening_iban": "NL81BUNQ2163127125",
        "postcode": "3077WD", "plaats": "Rotterdam", "rekeninghouder_naam": "JMM Reckman",
        "gedeelde_ruimtes": "keuken, badkamer, tuin", "extra_bcc": ["justin@example.com"],
        "verhuurders": [{"naam": "Jurian Reckman", "adres": "Batavierenplantsoen 33, Haarlem"}],
    }
    pand.update(pand_overrides or {})
    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([pand]))
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "beheerder": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []},
    }))
    config = Config(
        google_service_account_file="fake.json", properties_file=str(properties_file),
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file=str(users_file), flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14,
        smtp_host="smtp.example.com", smtp_port=587, smtp_username="info@steenhub.nl",
        smtp_password="geheim", smtp_from_email="info@steenhub.nl", smtp_from_naam="Steenhub",
        email_bcc=["jurian@example.com"],
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client, pand["slug"]


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    client, _slug = _maak_app_client(tmp_path, monkeypatch)
    return client


def _genereer_contract(client, pand_slug="mahoniestraat") -> str:
    """Genereert een contract, geeft de bestandsnaam van het (nog niet
    getekende) concept terug."""
    data = {
        "kamer": "1", "huurder_naam": "Bence Neumayer", "huurprijs": "870,00",
        "ingangsdatum": "2026-08-01", "borg": "1000,00", "email": "bence@example.com",
    }
    client.post(f"/pand/{pand_slug}/contracten/nieuw", data=data)
    resp = client.get(f"/pand/{pand_slug}/contracten")
    match = re.search(r'contracten/([^/"]+\.html)/pdf', resp.get_data(as_text=True))
    return match.group(1)


def _teken_af(client, pand_slug: str, bestandsnaam: str) -> str:
    """Stuurt het tekenverzoek en laat alle partijen (huurder + verhuurder)
    tekenen - geeft de bestandsnaam van de definitieve, GETEKENDE versie
    terug."""
    with patch("kamerverhuur_scanner.mailer.smtplib.SMTP") as mock_smtp_cls:
        mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
        client.post(f"/pand/{pand_slug}/contracten/{bestandsnaam}/tekenverzoek")
        ronde = ondertekenen.lees_ondertekenronde(pand_slug, bestandsnaam, ".")
        for o in ronde["ondertekenaars"]:
            client.post(
                f"/tekenen/{o['token']}",
                data={
                    "getekende_naam": o["naam"], "akkoord": "on",
                    "handtekening_data_url": TEST_HANDTEKENING_DATA_URL,
                },
            )
    ronde = ondertekenen.lees_ondertekenronde(pand_slug, bestandsnaam, ".")
    return ronde["getekend_bestandsnaam"]


def _genereer_en_teken_af(client, pand_slug="mahoniestraat") -> str:
    """Genereert een contract en tekent het meteen volledig af - geeft de
    bestandsnaam van de definitieve, GETEKENDE versie terug."""
    bestandsnaam = _genereer_contract(client, pand_slug)
    return _teken_af(client, pand_slug, bestandsnaam)


def _markeer_betaald(pand_slug: str) -> None:
    resultaat = TenantResult(
        tenant=KAMER_1, ontvangen_bedrag=Decimal("1870.00"), status=Status.BETAALD, gematchte_betalingen=[],
    )
    state.save(pand_slug, [resultaat], 0, ".")


def _markeer_niet_betaald(pand_slug: str) -> None:
    resultaat = TenantResult(
        tenant=KAMER_1, ontvangen_bedrag=Decimal("0.00"), status=Status.NIET_ONTVANGEN, gematchte_betalingen=[],
    )
    state.save(pand_slug, [resultaat], 0, ".")


def _bevestiging_url(pand_slug: str, bestandsnaam: str) -> str:
    return f"/pand/{pand_slug}/contracten/{bestandsnaam}/bevestiging"


# --- Zichtbaarheid van de knop op de Contracten-pagina ---


def test_bevestiging_knop_verschijnt_niet_zonder_afgeronde_ondertekening(app_client):
    _genereer_contract(app_client)
    _markeer_betaald("mahoniestraat")

    overzicht = app_client.get("/pand/mahoniestraat/contracten").get_data(as_text=True)
    assert "Mail bevestiging" not in overzicht


def test_bevestiging_knop_verschijnt_niet_zonder_betaling(app_client):
    _genereer_en_teken_af(app_client)
    _markeer_niet_betaald("mahoniestraat")

    overzicht = app_client.get("/pand/mahoniestraat/contracten").get_data(as_text=True)
    assert "Mail bevestiging" not in overzicht


def test_bevestiging_knop_verschijnt_pas_na_ondertekenen_en_betaling(app_client):
    getekend_bestandsnaam = _genereer_en_teken_af(app_client)
    _markeer_betaald("mahoniestraat")

    overzicht = app_client.get("/pand/mahoniestraat/contracten").get_data(as_text=True)
    assert "Mail bevestiging" in overzicht
    assert _bevestiging_url("mahoniestraat", getekend_bestandsnaam) in overzicht


# --- Route-bescherming ---


def test_contract_bevestiging_op_concept_geeft_foutmelding(app_client):
    bestandsnaam = _genereer_contract(app_client)
    _markeer_betaald("mahoniestraat")

    resp = app_client.get(_bevestiging_url("mahoniestraat", bestandsnaam), follow_redirects=True)
    assert resp.status_code == 200
    assert "nog niet volledig ondertekend" in resp.get_data(as_text=True).lower()


def test_contract_bevestiging_zonder_betaling_geeft_foutmelding(app_client):
    getekend_bestandsnaam = _genereer_en_teken_af(app_client)
    _markeer_niet_betaald("mahoniestraat")

    resp = app_client.get(_bevestiging_url("mahoniestraat", getekend_bestandsnaam), follow_redirects=True)
    assert resp.status_code == 200
    assert "betaling" in resp.get_data(as_text=True).lower()


# --- Regressie: concept (en dus zijn eigen metadata) al verwijderd na tekenen ---


def test_contract_bevestiging_werkt_nog_als_concept_verwijderd_is(app_client):
    bestandsnaam = _genereer_contract(app_client)
    getekend_bestandsnaam = _teken_af(app_client, "mahoniestraat", bestandsnaam)
    _markeer_betaald("mahoniestraat")

    # simuleert een oudere situatie (van vóór automatisch meekopiëren van
    # metadata naar de getekende versie) waarin het concept via "Verwijderen"
    # is opgeruimd - de getekende versie en de ondertekenronde blijven staan.
    contracts.verwijder_contract("mahoniestraat", bestandsnaam, ".")
    (contracts.output_dir("mahoniestraat", ".") / f"{getekend_bestandsnaam}.meta.json").unlink(missing_ok=True)

    overzicht = app_client.get("/pand/mahoniestraat/contracten").get_data(as_text=True)
    assert "Mail bevestiging" in overzicht

    resp = app_client.get(_bevestiging_url("mahoniestraat", getekend_bestandsnaam))
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Bold-uitnodigingslink" in body  # kwam gewoon tot een geldig voorbeeldscherm


# --- Bold-slot panden: verplichte uitnodigingslink ---


def test_contract_bevestiging_bold_slot_vraagt_eerst_om_link(app_client):
    getekend_bestandsnaam = _genereer_en_teken_af(app_client)
    _markeer_betaald("mahoniestraat")

    resp = app_client.get(_bevestiging_url("mahoniestraat", getekend_bestandsnaam))
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Bold-uitnodigingslink" in body
    assert 'name="onderwerp"' not in body  # nog geen voorbeeldscherm


def test_contract_bevestiging_bold_slot_toont_link_in_voorbeeld(app_client):
    getekend_bestandsnaam = _genereer_en_teken_af(app_client)
    _markeer_betaald("mahoniestraat")

    resp = app_client.get(
        _bevestiging_url("mahoniestraat", getekend_bestandsnaam),
        query_string={"bold_link": "https://bold.example/invite/xyz"},
    )
    body = resp.get_data(as_text=True)
    assert "https://bold.example/invite/xyz" in body
    assert 'name="onderwerp"' in body


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_contract_bevestiging_bold_slot_verstuurt_mail_met_link_en_bcc(mock_smtp_cls, app_client):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    getekend_bestandsnaam = _genereer_en_teken_af(app_client)
    _markeer_betaald("mahoniestraat")

    voorbeeld = app_client.get(
        _bevestiging_url("mahoniestraat", getekend_bestandsnaam),
        query_string={"bold_link": "https://bold.example/invite/xyz"},
    )
    body = voorbeeld.get_data(as_text=True)
    onderwerp = re.search(r'name="onderwerp" value="([^"]+)"', body).group(1)
    tekst = re.search(r'name="tekst"[^>]*>([\s\S]*?)</textarea>', body).group(1)

    resp = app_client.post(
        _bevestiging_url("mahoniestraat", getekend_bestandsnaam),
        data={"onderwerp": onderwerp, "tekst": tekst}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "verstuurd" in resp.get_data(as_text=True).lower()
    assert smtp_instance.send_message.call_count == 1
    verzonden = smtp_instance.send_message.call_args.args[0]
    assert verzonden["To"] == "bence@example.com"
    assert verzonden["Bcc"] == "jurian@example.com, justin@example.com"
    assert "https://bold.example/invite/xyz" in verzonden.get_content()


# --- Baumannlaan: sleutelbox-code, geen Bold-link nodig ---


def test_contract_bevestiging_baumannlaan_toont_sleutelbox_direct(tmp_path, monkeypatch):
    client, slug = _maak_app_client(
        tmp_path, monkeypatch,
        pand_overrides={"slug": "baumannlaan", "naam": "Burgemeester Baumannlaan 70b", "heeft_bold_slot": False},
    )
    getekend_bestandsnaam = _genereer_en_teken_af(client, pand_slug=slug)
    _markeer_betaald(slug)

    resp = client.get(_bevestiging_url(slug, getekend_bestandsnaam))
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "keybox" in body.lower()
    assert "1590" in body
    assert 'name="onderwerp"' in body  # geen tussenstap, meteen het voorbeeldscherm


# --- Validatie bij versturen ---


def test_contract_bevestiging_post_lege_tekst_geeft_foutmelding(app_client):
    getekend_bestandsnaam = _genereer_en_teken_af(app_client)
    _markeer_betaald("mahoniestraat")
    app_client.get(
        _bevestiging_url("mahoniestraat", getekend_bestandsnaam), query_string={"bold_link": "https://bold.example/x"}
    )

    resp = app_client.post(
        _bevestiging_url("mahoniestraat", getekend_bestandsnaam),
        data={"onderwerp": "", "tekst": ""}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "verplicht" in resp.get_data(as_text=True).lower()
