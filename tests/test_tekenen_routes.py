"""Route-tests voor het elektronisch laten ondertekenen van een
huurcontract: verzoek tot tekenen versturen, de publieke ondertekenpagina,
en het automatisch afronden (definitieve PDF + mail) zodra iedereen heeft
getekend."""
import html
import json
import re
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Tenant
from webapp import ondertekenen
from webapp.app import create_app

# minimale geldige 1x1-PNG (transparant), als data-URL - staat in voor een
# echte canvas-handtekening in tests die de ondertekenpagina POSTen.
TEST_HANDTEKENING_DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

KAMER_1 = Tenant(row_index=2, naam="Bence Neumayer", kamer="1", verwacht_bedrag=Decimal("930.00"))


class FakeSheetClient:
    laatste_update = None
    archiveer_aangeroepen_met = None

    def __init__(self, _config, _pand):
        pass

    def get_kamers(self):
        return [KAMER_1]

    def update_kamer(self, **kwargs):
        FakeSheetClient.laatste_update = kwargs

    def archiveer_vertrokken_huurder(self, kamer):
        FakeSheetClient.archiveer_aangeroepen_met = kamer

    def get_recent_vertrokken_huurders(self):
        return []


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import webapp.app as appmodule
    monkeypatch.setattr(appmodule, "SheetClient", FakeSheetClient)
    monkeypatch.chdir(tmp_path)
    FakeSheetClient.laatste_update = None
    FakeSheetClient.archiveer_aangeroepen_met = None

    properties_file = tmp_path / "properties.json"
    properties_file.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "fake",
         "bunq_rekening_iban": "NL81BUNQ2163127125",
         "postcode": "3077WD", "plaats": "Rotterdam", "rekeninghouder_naam": "JMM Reckman",
         "gedeelde_ruimtes": "keuken, badkamer, tuin", "extra_bcc": ["justin@example.com"],
         "verhuurders": [
             {"naam": "Jurian Reckman", "adres": "Batavierenplantsoen 33, Haarlem"},
             {"naam": "Justin Winkelman", "adres": "Rijksstraatweg 98, Haarlem"},
         ]},
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
        smtp_host="smtp.example.com", smtp_port=587, smtp_username="info@steenhub.nl",
        smtp_password="geheim", smtp_from_email="info@steenhub.nl", smtp_from_naam="Steenhub",
        email_bcc=["jurian@example.com", "justin@example.com"],
        email_bcc_beheerder=["jurian@example.com"],
    )
    app = create_app(config)
    app.testing = True
    client = app.test_client()
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    return client


def _genereer_en_haal_bestandsnaam(app_client, **overrides):
    data = {
        "kamer": "1", "huurder_naam": "Bence Neumayer", "huurprijs": "930,00",
        "ingangsdatum": "2026-07-10", "borg": "1000,00", "email": "bence@example.com",
    }
    data.update(overrides)
    app_client.post("/pand/mahoniestraat/contracten/nieuw", data=data)
    resp = app_client.get("/pand/mahoniestraat/contracten")
    match = re.search(r'contracten/([^/"]+\.html)/pdf', resp.get_data(as_text=True))
    assert match
    return match.group(1)


def _tokens(bestandsnaam):
    ronde = ondertekenen.lees_ondertekenronde("mahoniestraat", bestandsnaam, ".")
    return {o["rol"] + ("-2" if o["rol"] == "verhuurder" and o["naam"] == "Justin Winkelman" else ""): o
            for o in ronde["ondertekenaars"]}


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenverzoek_mailt_huurder_en_beide_verhuurders(mock_smtp_cls, app_client):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)

    resp = app_client.post(
        f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek", follow_redirects=True
    )
    assert resp.status_code == 200
    assert "verstuurd" in resp.get_data(as_text=True).lower()
    assert smtp_instance.send_message.call_count == 3  # huurder + 2 verhuurders

    ontvangers = {call.args[0]["To"] for call in smtp_instance.send_message.call_args_list}
    assert ontvangers == {"bence@example.com", "jurian@example.com", "justin@example.com"}

    huurder_bericht = next(
        call.args[0] for call in smtp_instance.send_message.call_args_list if call.args[0]["To"] == "bence@example.com"
    )
    tekst = huurder_bericht.get_content()
    assert "/tekenen/" in tekst
    # borg 1000 + pro-rata huur (930 * 22/31 dagen, 10-31 juli) = 1000 + 660,00 = 1660,00 -
    # en het sommetje moet duidelijk uitgesplitst zijn, niet alleen het totaal
    assert "1.660,00" in tekst
    assert "Security deposit: EUR 1.000,00" in tekst
    assert "Pro-rated rent from 10-07-2026 to 31-07-2026 (22 days): EUR 660,00" in tekst


def test_tekenverzoek_get_toont_voorbeeldscherm_zonder_te_mailen(app_client):
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)

    resp = app_client.get(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Verzoek tot tekenen" in body
    assert "/tekenen/" in body  # de echte tekenlink van de huurder, voor het voorbeeld
    assert "Jurian Reckman" in body
    assert "Justin Winkelman" in body

    # er is nog niets gemaild, en de Contracten-pagina toont dus nog de
    # "Verzoek tot tekenen"-link i.p.v. een ondertekenstatus-link
    overzicht = app_client.get("/pand/mahoniestraat/contracten").get_data(as_text=True)
    assert "Verzoek tot tekenen" in overzicht
    assert "Ondertekenstatus" not in overzicht


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenverzoek_post_gebruikt_aangepaste_tekst(mock_smtp_cls, app_client):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)

    resp = app_client.post(
        f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek",
        data={"onderwerp": "Aangepast onderwerp", "tekst": "Aangepaste tekst met een link erin."},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    huurder_bericht = next(
        call.args[0] for call in smtp_instance.send_message.call_args_list if call.args[0]["To"] == "bence@example.com"
    )
    assert huurder_bericht["Subject"] == "Aangepast onderwerp"
    assert "Aangepaste tekst met een link erin." in huurder_bericht.get_content()

    # de Contracten-pagina schakelt nu wel over naar de ondertekenstatus-link
    overzicht = app_client.get("/pand/mahoniestraat/contracten").get_data(as_text=True)
    assert "Ondertekenstatus" in overzicht


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenverzoek_met_vinkje_schrijft_terug_naar_sheet(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)

    app_client.post(
        f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek",
        data={"schrijf_terug_naar_sheet": "on"},
    )
    assert FakeSheetClient.laatste_update is not None
    assert FakeSheetClient.laatste_update["naam"] == "Bence Neumayer"


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenverzoek_zonder_vinkje_laat_sheet_ongemoeid(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)

    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    assert FakeSheetClient.laatste_update is None


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenverzoek_is_idempotent(mock_smtp_cls, app_client):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)

    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")

    assert smtp_instance.send_message.call_count == 3  # niet 6


def test_tekenverzoek_zonder_emailadres_huurder_geeft_foutmelding(app_client):
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client, email="")
    resp = app_client.post(
        f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek", follow_redirects=True
    )
    assert resp.status_code == 200
    assert "geen e-mailadres" in resp.get_data(as_text=True).lower()
    assert ondertekenen.lees_ondertekenronde("mahoniestraat", bestandsnaam, ".") is None


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_ondertekenstatus_toont_alle_ondertekenaars(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")

    resp = app_client.get(f"/pand/mahoniestraat/contracten/{bestandsnaam}/ondertekenstatus")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Bence Neumayer" in body
    assert "Jurian Reckman" in body
    assert "Justin Winkelman" in body
    assert "Nog niet getekend" in body


def test_ondertekenstatus_zonder_verzoek_geeft_404(app_client):
    resp = app_client.get("/pand/mahoniestraat/contracten/bestaat-niet.html/ondertekenstatus")
    assert resp.status_code == 404


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenpagina_toont_formulier_en_iframe(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)

    resp = app_client.get(f"/tekenen/{tokens['huurder']['token']}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Sign rental agreement" in body
    assert "tenant" in body
    assert f"/tekenen/{tokens['huurder']['token']}/contract" in body
    # De blijvende (sticky) download-als-PDF-knop bovenaan.
    assert "Download as PDF" in body
    assert f"/tekenen/{tokens['huurder']['token']}/pdf" in body


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenen_pdf_download_werkt_met_geldige_token(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)

    resp = app_client.get(f"/tekenen/{tokens['huurder']['token']}/pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:4] == b"%PDF"


def test_tekenen_pdf_onbekende_token_geeft_404(app_client):
    assert app_client.get("/tekenen/onbekende-token-xyz/pdf").status_code == 404


def test_tekenen_onbekende_token_geeft_404(app_client):
    resp = app_client.get("/tekenen/onbekende-token-xyz")
    assert resp.status_code == 404


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenen_post_registreert_handtekening(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)

    resp = app_client.post(
        f"/tekenen/{tokens['huurder']['token']}",
        data={"getekende_naam": "Bence Neumayer", "akkoord": "on", "handtekening_data_url": TEST_HANDTEKENING_DATA_URL},
        environ_overrides={"REMOTE_ADDR": "203.0.113.5"},
    )
    assert resp.status_code == 200
    assert "you've signed" in resp.get_data(as_text=True).lower()

    ronde = ondertekenen.lees_ondertekenronde("mahoniestraat", bestandsnaam, ".")
    huurder = next(o for o in ronde["ondertekenaars"] if o["rol"] == "huurder")
    assert huurder["ondertekend_op"] is not None
    assert huurder["ip_adres"] == "203.0.113.5"
    assert huurder["getekende_naam"] == "Bence Neumayer"
    assert huurder["handtekening_png_base64"]
    assert ondertekenen.alles_getekend(ronde) is False  # verhuurders nog niet


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenen_zonder_akkoordvakje_geeft_foutmelding(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)

    resp = app_client.post(
        f"/tekenen/{tokens['huurder']['token']}", data={"getekende_naam": "Bence Neumayer"}
    )
    assert resp.status_code == 200
    assert "tick the checkbox" in resp.get_data(as_text=True).lower()
    ronde = ondertekenen.lees_ondertekenronde("mahoniestraat", bestandsnaam, ".")
    huurder = next(o for o in ronde["ondertekenaars"] if o["rol"] == "huurder")
    assert huurder["ondertekend_op"] is None


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenen_zonder_handtekening_geeft_foutmelding(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)

    resp = app_client.post(
        f"/tekenen/{tokens['huurder']['token']}",
        data={"getekende_naam": "Bence Neumayer", "akkoord": "on"},  # geen handtekening_data_url
    )
    assert resp.status_code == 200
    assert "draw your signature" in resp.get_data(as_text=True).lower()
    ronde = ondertekenen.lees_ondertekenronde("mahoniestraat", bestandsnaam, ".")
    huurder = next(o for o in ronde["ondertekenaars"] if o["rol"] == "huurder")
    assert huurder["ondertekend_op"] is None


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenen_dubbel_indienen_blijft_bij_eerste_handtekening(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)
    token = tokens["huurder"]["token"]

    app_client.post(
        f"/tekenen/{token}",
        data={"getekende_naam": "Bence Neumayer", "akkoord": "on", "handtekening_data_url": TEST_HANDTEKENING_DATA_URL},
    )
    resp = app_client.get(f"/tekenen/{token}")
    assert resp.status_code == 200
    assert "you've signed" in resp.get_data(as_text=True).lower()


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenen_contract_route_toont_html(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)

    resp = app_client.get(f"/tekenen/{tokens['huurder']['token']}/contract")
    assert resp.status_code == 200
    assert "Bence Neumayer" in resp.get_data(as_text=True)


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_alle_partijen_tekenen_rondt_af_met_getekend_contract_en_mail(mock_smtp_cls, app_client):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)
    smtp_instance.send_message.reset_mock()

    for rol_sleutel, naam in [("huurder", "Bence Neumayer"), ("verhuurder", "Jurian Reckman"), ("verhuurder-2", "Justin Winkelman")]:
        resp = app_client.post(
            f"/tekenen/{tokens[rol_sleutel]['token']}",
            data={"getekende_naam": naam, "akkoord": "on", "handtekening_data_url": TEST_HANDTEKENING_DATA_URL},
        )
        assert resp.status_code == 200

    ronde = ondertekenen.lees_ondertekenronde("mahoniestraat", bestandsnaam, ".")
    assert ronde["afgerond_op"] is not None
    getekend_bestandsnaam = ronde["getekend_bestandsnaam"]
    assert getekend_bestandsnaam == bestandsnaam.replace(".html", "-getekend.html")

    # het definitieve contract staat nu op de Contracten-pagina, met badge
    overzicht = app_client.get("/pand/mahoniestraat/contracten").get_data(as_text=True)
    assert getekend_bestandsnaam in overzicht
    assert "Getekend" in overzicht

    # de getekende handtekeningen (canvas-afbeeldingen) staan in het definitieve contract
    getekend_html = app_client.get(
        f"/pand/mahoniestraat/contracten/{getekend_bestandsnaam}"
    ).get_data(as_text=True)
    assert "data:image/png;base64," in getekend_html
    assert getekend_html.count("data:image/png;base64,") == 3  # huurder + 2 verhuurders

    # mail 3: het ondertekende contract als PDF-bijlage naar alle 3 partijen,
    # elk met een eigen aanhef/inhoud passend bij hun rol
    berichten = {call.args[0]["To"]: call.args[0] for call in smtp_instance.send_message.call_args_list}
    assert set(berichten) == {"bence@example.com", "jurian@example.com", "justin@example.com"}
    for bericht in berichten.values():
        bijlagen = list(bericht.iter_attachments())
        assert len(bijlagen) == 1
        assert bijlagen[0].get_content_type() == "application/pdf"

    assert "Signed rental agreement" in berichten["bence@example.com"]["Subject"]
    huurder_tekst = berichten["bence@example.com"].get_body(("plain",)).get_content()
    assert huurder_tekst.startswith("Dear Bence Neumayer,")

    for adres, naam in [("jurian@example.com", "Jurian Reckman"), ("justin@example.com", "Justin Winkelman")]:
        assert "Getekend huurcontract" in berichten[adres]["Subject"]
        tekst = berichten[adres].get_body(("plain",)).get_content()
        assert tekst.startswith(f"Beste {naam},")
        assert "Documenten" in tekst


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_alle_partijen_tekenen_uploadt_getekend_contract_naar_drive(mock_smtp_cls, app_client, monkeypatch):
    import webapp.app as appmodule

    uploads = []
    monkeypatch.setattr(
        appmodule.drive_sync, "upload_bestand",
        lambda config, pand, huurder_naam, bestandsnaam, inhoud: uploads.append((pand.slug, huurder_naam, bestandsnaam)),
    )
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)

    for rol_sleutel, naam in [("huurder", "Bence Neumayer"), ("verhuurder", "Jurian Reckman"), ("verhuurder-2", "Justin Winkelman")]:
        app_client.post(
            f"/tekenen/{tokens[rol_sleutel]['token']}",
            data={"getekende_naam": naam, "akkoord": "on", "handtekening_data_url": TEST_HANDTEKENING_DATA_URL},
        )

    assert len(uploads) == 1
    pand_slug, huurder_naam, geuploade_bestandsnaam = uploads[0]
    assert pand_slug == "mahoniestraat"
    assert huurder_naam == "Bence Neumayer"
    assert geuploade_bestandsnaam.endswith(".pdf")


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_tekenverzoek_op_al_getekend_contract_geeft_foutmelding(mock_smtp_cls, app_client):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)
    for rol_sleutel, naam in [("huurder", "Bence Neumayer"), ("verhuurder", "Jurian Reckman"), ("verhuurder-2", "Justin Winkelman")]:
        app_client.post(
            f"/tekenen/{tokens[rol_sleutel]['token']}",
            data={"getekende_naam": naam, "akkoord": "on", "handtekening_data_url": TEST_HANDTEKENING_DATA_URL},
        )
    ronde = ondertekenen.lees_ondertekenronde("mahoniestraat", bestandsnaam, ".")
    getekend_bestandsnaam = ronde["getekend_bestandsnaam"]

    resp = app_client.post(
        f"/pand/mahoniestraat/contracten/{getekend_bestandsnaam}/tekenverzoek", follow_redirects=True
    )
    assert resp.status_code == 200
    assert "al een ondertekend contract" in resp.get_data(as_text=True).lower()


def _opnieuw_mailen_url(bestandsnaam, ondertekenaar_id):
    return f"/pand/mahoniestraat/contracten/{bestandsnaam}/ondertekenstatus/{ondertekenaar_id}/opnieuw-mailen"


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_opnieuw_mailen_get_toont_voorbeeld_met_beide_boxjes_aangevinkt(mock_smtp_cls, app_client):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)
    smtp_instance.send_message.reset_mock()

    resp = app_client.get(_opnieuw_mailen_url(bestandsnaam, tokens["huurder"]["id"]))
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "We have not yet received your payment" in body
    assert "We have not yet received your signature" in body
    # nog niets gemaild - alleen een voorbeeld
    smtp_instance.send_message.assert_not_called()


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_opnieuw_mailen_get_met_alleen_onderteken_bevestigt_betaling(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)

    resp = app_client.get(
        _opnieuw_mailen_url(bestandsnaam, tokens["huurder"]["id"]) + "?onderteken=1&betaal=0"
    )
    body = resp.get_data(as_text=True)
    assert "We have received your payment" in body
    assert "We have not yet received your signature" in body


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_opnieuw_mailen_post_stuurt_alleen_naar_1_ondertekenaar_met_beheerder_bcc(mock_smtp_cls, app_client):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)
    smtp_instance.send_message.reset_mock()

    voorbeeld = app_client.get(_opnieuw_mailen_url(bestandsnaam, tokens["huurder"]["id"]))
    body = voorbeeld.get_data(as_text=True)
    onderwerp = html.unescape(re.search(r'name="onderwerp" value="([^"]+)"', body).group(1))
    tekst = html.unescape(re.search(r'name="tekst"[^>]*>([\s\S]*?)</textarea>', body).group(1))

    resp = app_client.post(
        _opnieuw_mailen_url(bestandsnaam, tokens["huurder"]["id"]),
        data={"onderwerp": onderwerp, "tekst": tekst},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "opnieuw gemaild" in resp.get_data(as_text=True).lower()
    assert smtp_instance.send_message.call_count == 1
    verzonden_bericht = smtp_instance.send_message.call_args.args[0]
    assert verzonden_bericht["To"] == "bence@example.com"
    # smallere BCC dan de rest van de app (email_bcc_beheerder, niet Justin)
    assert verzonden_bericht["Bcc"] == "jurian@example.com"


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_opnieuw_mailen_verhuurder_krijgt_alleen_tekenherinnering(mock_smtp_cls, app_client):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)

    resp = app_client.get(_opnieuw_mailen_url(bestandsnaam, tokens["verhuurder"]["id"]))
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "we have not yet received your signature" in body.lower()
    assert "onderteken herinnering" not in body.lower()  # geen boxjes voor niet-huurders


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_opnieuw_mailen_op_al_getekende_ondertekenaar_geeft_foutmelding(mock_smtp_cls, app_client):
    mock_smtp_cls.return_value.__enter__.return_value = MagicMock()
    bestandsnaam = _genereer_en_haal_bestandsnaam(app_client)
    app_client.post(f"/pand/mahoniestraat/contracten/{bestandsnaam}/tekenverzoek")
    tokens = _tokens(bestandsnaam)
    app_client.post(
        f"/tekenen/{tokens['huurder']['token']}",
        data={"getekende_naam": "Bence Neumayer", "akkoord": "on", "handtekening_data_url": TEST_HANDTEKENING_DATA_URL},
    )

    resp = app_client.get(_opnieuw_mailen_url(bestandsnaam, tokens["huurder"]["id"]), follow_redirects=True)
    assert resp.status_code == 200
    assert "had al getekend" in resp.get_data(as_text=True).lower()
