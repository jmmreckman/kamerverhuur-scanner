"""Integratietests voor de publieke aanbodpagina + aanmeldformulier, en de
admin-kant (aanbod beheren, aanmeldingen-overzicht), met een nep-Sheetclient
en lokale mediaopslag (tmp_path) in plaats van Google Drive."""
import io
import json
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.lokale_media import LokaleMediaClient
from kamerverhuur_scanner.mailer import MailError
from kamerverhuur_scanner.models import Pand, Tenant
from webapp.app import create_app

KAMER_BESCHIKBAAR = Tenant(
    row_index=2, naam="", kamer="1", verwacht_bedrag=Decimal("650.00"),
    beschikbaar=True, advertentie_omschrijving="A nice room",
)
KAMER_VERHUURD = Tenant(
    row_index=3, naam="Jan Jansen", kamer="2", verwacht_bedrag=Decimal("700.00"), beschikbaar=False,
    email="jan@example.com",
)
KAMER_MET_ADVERTENTIEVELDEN = Tenant(
    row_index=4, naam="", kamer="3", verwacht_bedrag=Decimal("650.00"),
    beschikbaar=True, advertentie_omschrijving="Nice room with extras",
    advertentie_prijs=Decimal("725.00"), advertentie_oppervlakte="18 m²",
    advertentie_beschikbaar_per="01-09-2026", advertentie_beschikbaar_tot="01-07-2027",
    advertentie_borg=Decimal("1000.00"),
)


class FakeSheetClient:
    def __init__(self, _config, pand):
        self.pand = pand
        self.aanmeldingen = []
        self.bezichtigingen = []
        self.laatste_update_aanbod = None

    def get_kamers(self):
        return [KAMER_BESCHIKBAAR, KAMER_VERHUURD, KAMER_MET_ADVERTENTIEVELDEN]

    def get_tenants(self):
        return [k for k in self.get_kamers() if k.naam]

    def get_recent_vertrokken_huurders(self, dagen=31):
        return []

    def get_geschiedenis(self, kamer):
        return []

    laat_update_aanbod_falen = False

    def update_aanbod(
        self, row_index, beschikbaar, omschrijving, map_id,
        prijs=None, oppervlakte=None, beschikbaar_per=None, beschikbaar_tot=None, borg=None,
    ):
        if self.laat_update_aanbod_falen:
            raise RuntimeError("simuleert een mislukte Google Sheets-schrijfactie")
        self.laatste_update_aanbod = {
            "row_index": row_index, "beschikbaar": beschikbaar, "omschrijving": omschrijving, "map_id": map_id,
            "prijs": prijs, "oppervlakte": oppervlakte, "beschikbaar_per": beschikbaar_per,
            "beschikbaar_tot": beschikbaar_tot, "borg": borg,
        }

    def add_aanmelding(self, kamer, aanmelding):
        self.aanmeldingen.append((kamer, aanmelding))

    def get_aanmeldingen(self):
        # zelfde kolomvolgorde als SheetClient.add_aanmelding()
        return [
            [
                "10-07-2026", kamer, a.naam, a.email, a.telefoon, a.huidig_adres, a.studie,
                a.studentnummer, a.gewenste_ingangsdatum, a.gewenste_huurduur, a.inkomstenbron,
                a.inkomsten_bedrag, a.borgsteller, a.bezichtiging, a.videobel_nummer,
                a.bewijs_inschrijving_link, a.borgsteller_naam, a.borgsteller_relatie, a.borgsteller_email,
            ]
            for kamer, a in self.aanmeldingen
        ]

    def wis_aanmeldingen(self):
        self.aanmeldingen = []

    def add_bezichtiging(self, datum_iso, afspraak):
        self.bezichtigingen.append((datum_iso, dict(afspraak)))

    def get_bezichtigingen(self):
        return [
            [
                datum_iso, a["tijd_start"], a["tijd_eind"], a["kamer"], a["naam"], a["email"],
                a["telefoon"], a["bezichtiging"], a["bel_nummer"], "10-07-2026 12:00",
            ]
            for datum_iso, a in self.bezichtigingen
        ]

    def get_bezichtigingen_met_rijnummer(self):
        return list(enumerate(self.get_bezichtigingen(), start=2))

    def verwijder_bezichtiging(self, rijnummer):
        del self.bezichtigingen[rijnummer - 2]


_fake_sheet_singleton = {}


def _fake_sheet_factory(config, pand):
    if pand.slug not in _fake_sheet_singleton:
        _fake_sheet_singleton[pand.slug] = FakeSheetClient(config, pand)
    return _fake_sheet_singleton[pand.slug]


_file_id = {}


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
        email_bcc_beheerder=["jmmreckman@gmail.com"],
    )
    config_velden.update(config_overrides or {})
    config = Config(**config_velden)
    pand = Pand(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="fake",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        google_drive_folder_id=None, bunq_rekening_iban="NL81BUNQ2163127125",
    )
    _file_id["1"] = LokaleMediaClient(config, pand, "aanbod").upload_bestand(
        "1", "foto.jpg", "image/jpeg", b"fake-image-bytes"
    )

    app = create_app(config)
    app.testing = True
    return app.test_client()


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


VOLLEDIG_FORMULIER = {
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+31612345678",
    "current_address": "Somestreet 1, Rotterdam",
    "study_program": "Computer Science",
    "student_number": "123456",
    "desired_start_date": "2026-09-01",
    "desired_contract_duration": "12 months",
    "income_source": "Parents",
    "income_amount": "1200",
    "guarantor": "Yes",
    "guarantor_name": "John Doe",
    "guarantor_relation": "Father",
    "guarantor_email": "john@example.com",
    "viewing_preference": "in_person",
    "agree_rules": "on",
}


def test_aanbod_overzicht_toont_alleen_beschikbare_kamers(app_client):
    resp = app_client.get("/aanbod")
    assert resp.status_code == 200
    assert b"Mahoniestraat 15" in resp.data
    assert b"room 1" in resp.data
    assert b"room 2" not in resp.data


def test_aanbod_detail_van_verhuurde_kamer_geeft_404(app_client):
    resp = app_client.get("/aanbod/mahoniestraat/2")
    assert resp.status_code == 404


def test_aanbod_detail_van_beschikbare_kamer_werkt(app_client):
    resp = app_client.get("/aanbod/mahoniestraat/1")
    assert resp.status_code == 200
    assert b"A nice room" in resp.data
    assert b"Apply for this room" in resp.data


def test_aanbod_media_alleen_voor_bekende_bestanden(app_client):
    ok = app_client.get(f"/aanbod/mahoniestraat/1/media/{_file_id['1']}")
    assert ok.status_code == 200
    onbekend = app_client.get("/aanbod/mahoniestraat/1/media/ander-bestand")
    assert onbekend.status_code == 404


def test_apply_form_zonder_verplichte_velden_geeft_fout(app_client):
    resp = app_client.post("/aanbod/mahoniestraat/1/apply", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert b"Please fill in" in resp.data


def test_apply_form_volledig_ingevuld_slaagt(app_client):
    data = dict(VOLLEDIG_FORMULIER)
    data["study_proof"] = (io.BytesIO(b"fake-pdf-bytes"), "enrollment.pdf")
    resp = app_client.post("/aanbod/mahoniestraat/1/apply", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Thank you for your application" in resp.data
    sheet = _fake_sheet_singleton["mahoniestraat"]
    assert len(sheet.aanmeldingen) == 1
    kamer, aanmelding = sheet.aanmeldingen[0]
    assert kamer == "1"
    assert aanmelding.naam == "Jane Doe"
    assert aanmelding.bewijs_inschrijving_link.startswith("/pand/mahoniestraat/aanmeldingen/bewijs/1/")


def test_apply_form_op_verhuurde_kamer_geeft_404(app_client):
    resp = app_client.get("/aanbod/mahoniestraat/2/apply")
    assert resp.status_code == 404


# --- Meldingsmail bij nieuwe aanmelding (alleen naar de beheerder, niet naar alle mede-eigenaren) ---


def test_nieuwe_aanmelding_mailt_alleen_de_beheerder(app_client, verstuurde_mails):
    data = dict(VOLLEDIG_FORMULIER)
    data["study_proof"] = (io.BytesIO(b"fake-pdf-bytes"), "enrollment.pdf")
    app_client.post("/aanbod/mahoniestraat/1/apply", data=data, content_type="multipart/form-data")

    assert len(verstuurde_mails) == 1
    mail = verstuurde_mails[0]
    assert mail["aan"] == "jmmreckman@gmail.com"
    assert mail["bcc"] == []  # expliciet leeg - geen mede-eigenaren erbij via de standaard-BCC
    assert "justin@example.com" not in mail["aan"]
    assert "Jane Doe" in mail["tekst"]
    assert "kamer 1" in mail["onderwerp"].lower()
    assert "Mahoniestraat 15" in mail["onderwerp"]


def test_nieuwe_aanmelding_zonder_beheerder_bcc_valt_terug_op_email_bcc(tmp_path, monkeypatch, verstuurde_mails):
    client = _bouw_app_client(tmp_path, monkeypatch, config_overrides={"email_bcc_beheerder": []})

    data = dict(VOLLEDIG_FORMULIER)
    data["study_proof"] = (io.BytesIO(b"fake-pdf-bytes"), "enrollment.pdf")
    client.post("/aanbod/mahoniestraat/1/apply", data=data, content_type="multipart/form-data")

    assert len(verstuurde_mails) == 1
    assert verstuurde_mails[0]["aan"] == "jurian@example.com, justin@example.com"


def test_nieuwe_aanmelding_mislukte_mail_breekt_de_aanmelding_niet(app_client, monkeypatch):
    import webapp.app as appmodule

    def _falende_mailer(config, aan, onderwerp, tekst, bcc=None):
        raise MailError("SMTP tijdelijk niet bereikbaar")

    monkeypatch.setattr(appmodule, "verstuur_email", _falende_mailer)

    data = dict(VOLLEDIG_FORMULIER)
    data["study_proof"] = (io.BytesIO(b"fake-pdf-bytes"), "enrollment.pdf")
    resp = app_client.post(
        "/aanbod/mahoniestraat/1/apply", data=data, content_type="multipart/form-data", follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"Thank you for your application" in resp.data
    assert len(_fake_sheet_singleton["mahoniestraat"].aanmeldingen) == 1


def test_kamer_aanbod_beheren_vereist_login(app_client):
    resp = app_client.get("/pand/mahoniestraat/kamers/1/aanbod", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_kamer_aanbod_beheren_toont_media_en_omschrijving(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.get("/pand/mahoniestraat/kamers/1/aanbod")
    assert resp.status_code == 200
    assert b"A nice room" in resp.data
    assert b"foto.jpg" in resp.data


def test_kamer_aanbod_thumbnail_wijst_naar_inline_route_niet_naar_download(app_client):
    # Regressietest: de <img> op deze pagina moet naar een inline-route wijzen.
    # Eerder wees hij naar documenten_download, die Content-Disposition: attachment
    # meestuurt - daardoor tonen browsers geen thumbnail, alleen een gebroken icoon.
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.get("/pand/mahoniestraat/kamers/1/aanbod")
    body = resp.get_data(as_text=True)
    assert f"/aanbod/{_file_id['1']}/weergeven" in body
    assert f"/documenten/{_file_id['1']}/download" not in body


def test_kamer_aanbod_media_toont_inline_zonder_attachment_header(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.get(f"/pand/mahoniestraat/kamers/1/aanbod/{_file_id['1']}/weergeven")
    assert resp.status_code == 200
    assert resp.data == b"fake-image-bytes"
    assert resp.mimetype == "image/jpeg"
    assert "Content-Disposition" not in resp.headers


def test_kamer_aanbod_media_onbekend_bestand_geeft_404(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.get("/pand/mahoniestraat/kamers/1/aanbod/onbekend-id/weergeven")
    assert resp.status_code == 404


def test_aanmeldingen_overzicht_en_wissen(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    data = dict(VOLLEDIG_FORMULIER)
    data["study_proof"] = (io.BytesIO(b"fake-pdf-bytes"), "enrollment.pdf")
    app_client.post("/aanbod/mahoniestraat/1/apply", data=data, content_type="multipart/form-data")

    resp = app_client.get("/pand/mahoniestraat/aanmeldingen")
    body = resp.get_data(as_text=True)
    assert "Jane Doe" in body
    # "Contract maken" moet ALLE gegevens van de aanmelding (incl. borgsteller) meegeven
    assert "huurder_naam=Jane+Doe" in body
    assert "studentnummer=123456" in body
    assert "studierichting=Computer+Science" in body
    assert "email=jane@example.com" in body
    assert "borgsteller_naam=John+Doe" in body
    assert "borgsteller_relatie=Father" in body
    assert "borgsteller_email=john@example.com" in body

    app_client.post("/pand/mahoniestraat/aanmeldingen/wissen")
    resp = app_client.get("/pand/mahoniestraat/aanmeldingen")
    assert b"Jane Doe" not in resp.data
    assert b"Nog geen aanmeldingen" in resp.data


# --- Aanpasbare advertentievelden (prijs, oppervlakte, beschikbaarheid, borg) ---


def test_aanbod_detail_toont_advertentievelden_ipv_gewone_huur(app_client):
    resp = app_client.get("/aanbod/mahoniestraat/3")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "€725,00" in body  # advertentieprijs, niet de gewone €650,00 huur
    assert "€650,00" not in body
    assert "18 m²" in body
    assert "available from 01-09-2026 to 01-07-2027" in body
    assert "Security deposit: €1.000,00" in body


def test_aanbod_detail_zonder_advertentievelden_valt_terug_op_gewone_huur(app_client):
    resp = app_client.get("/aanbod/mahoniestraat/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "€650,00" in body  # gewone "Totale huur", geen advertentieprijs ingevuld
    assert "Security deposit" not in body  # ook geen (advertentie)borg bekend


def test_aanbod_overzicht_toont_advertentieprijs_en_oppervlakte(app_client):
    resp = app_client.get("/aanbod")
    body = resp.get_data(as_text=True)
    assert "€725,00" in body
    assert "18 m²" in body


def test_kamer_aanbod_beheren_toont_advertentievelden(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.get("/pand/mahoniestraat/kamers/3/aanbod")
    body = resp.get_data(as_text=True)
    assert 'value="€725,00"' in body
    assert 'value="18 m²"' in body
    assert 'value="01-09-2026"' in body
    assert 'value="01-07-2027"' in body
    assert 'value="€1.000,00"' in body


def test_kamer_aanbod_beheren_post_slaat_advertentievelden_op(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    app_client.post(
        "/pand/mahoniestraat/kamers/1/aanbod",
        data={
            "beschikbaar": "on", "omschrijving": "A nice room",
            "advertentie_prijs": "725,00", "advertentie_oppervlakte": "18 m²",
            "advertentie_beschikbaar_per": "01-09-2026", "advertentie_beschikbaar_tot": "01-07-2027",
            "advertentie_borg": "1.000,00",
        },
    )
    opgeslagen = _fake_sheet_singleton["mahoniestraat"].laatste_update_aanbod
    assert opgeslagen["prijs"] == Decimal("725.00")
    assert opgeslagen["oppervlakte"] == "18 m²"
    assert opgeslagen["beschikbaar_per"] == "01-09-2026"
    assert opgeslagen["beschikbaar_tot"] == "01-07-2027"
    assert opgeslagen["borg"] == Decimal("1000.00")


def test_kamer_aanbod_beheren_post_zonder_advertentievelden_slaat_none_op(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    app_client.post(
        "/pand/mahoniestraat/kamers/1/aanbod",
        data={"beschikbaar": "on", "omschrijving": "A nice room"},
    )
    opgeslagen = _fake_sheet_singleton["mahoniestraat"].laatste_update_aanbod
    assert opgeslagen["prijs"] is None
    assert opgeslagen["oppervlakte"] is None
    assert opgeslagen["borg"] is None


def test_kamer_aanbod_beheren_post_accepteert_rond_bedrag_zonder_centen(app_client):
    # Regressietest: "725,-" (gangbare NL-notatie voor een rond bedrag) gaf
    # eerder een onafgevangen crash (kale 500-fout) i.p.v. gewoon op te slaan.
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/aanbod",
        data={
            "beschikbaar": "on", "omschrijving": "A nice room",
            "advertentie_prijs": "725,-", "advertentie_borg": "1.000,-",
        },
    )
    assert resp.status_code == 302
    opgeslagen = _fake_sheet_singleton["mahoniestraat"].laatste_update_aanbod
    assert opgeslagen["prijs"] == Decimal("725.00")
    assert opgeslagen["borg"] == Decimal("1000.00")


def test_kamer_aanbod_beheren_post_onleesbaar_bedrag_geeft_foutmelding_niet_500(app_client):
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/aanbod",
        data={"beschikbaar": "on", "omschrijving": "A nice room", "advertentie_prijs": "geen bedrag"},
    )
    assert resp.status_code == 200
    assert "niet lezen" in resp.get_data(as_text=True).lower()
    assert _fake_sheet_singleton["mahoniestraat"].laatste_update_aanbod is None


def test_kamer_aanbod_beheren_get_mislukte_medialijst_crasht_niet(app_client, monkeypatch):
    # Regressietest: als het ophalen van de foto-/videolijst faalt (bv. een
    # beschadigd .meta-bestand na veel uploads), mag de hele "Aanbod beheren"-
    # pagina niet crashen - alleen een lege lijst tonen met een melding.
    def _falende_list_bestanden(self, kamer):
        raise RuntimeError("simuleert een kapot .meta-bestand")

    monkeypatch.setattr(LokaleMediaClient, "list_bestanden", _falende_list_bestanden)
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    resp = app_client.get("/pand/mahoniestraat/kamers/1/aanbod")
    assert resp.status_code == 200
    assert "niet volledig geladen" in resp.get_data(as_text=True).lower()


def test_kamer_aanbod_beheren_mislukte_sheet_schrijfactie_geeft_foutmelding_niet_500(app_client):
    # Regressietest voor de gemelde "Internal Server Error": een fout bij het
    # schrijven naar de sheet (bv. een tijdelijke Google-API-hapering) mag
    # nooit als kale 500-crash eindigen, altijd als nette foutmelding.
    app_client.post("/login", data={"username": "beheerder", "password": "geheim123"})
    app_client.get("/pand/mahoniestraat/kamers/1/aanbod")  # instantieert de FakeSheetClient-singleton
    _fake_sheet_singleton["mahoniestraat"].laat_update_aanbod_falen = True
    resp = app_client.post(
        "/pand/mahoniestraat/kamers/1/aanbod",
        data={
            "beschikbaar": "on", "omschrijving": "A nice room",
            "advertentie_prijs": "919", "advertentie_oppervlakte": "19",
            "advertentie_beschikbaar_per": "01-08-2026", "advertentie_beschikbaar_tot": "31-07-2028",
            "advertentie_borg": "1402",
        },
    )
    assert resp.status_code == 200
    assert "mislukt" in resp.get_data(as_text=True).lower()
