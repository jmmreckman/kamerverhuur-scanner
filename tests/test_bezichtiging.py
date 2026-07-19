"""Integratietests voor het inplannen van een bezichtiging vanuit het
aanmeldingenoverzicht: aanmelders selecteren, een tijdvak invullen, het
voorstel controleren en bevestigen (bevestigingsmail per aanmelder + één
overzichtsmail naar alle beheerders)."""
import io

import pytest

from tests.test_aanbod_routes import VOLLEDIG_FORMULIER, _bouw_app_client, _fake_sheet_singleton
from webapp.bezichtiging import bel_nummer, bereken_planning, parse_aanmelder, serialiseer_aanmelder
from datetime import time


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


def _dien_aanmelding_in(client, naam="Jane Doe", email="jane@example.com", viewing="in_person"):
    data = dict(VOLLEDIG_FORMULIER)
    data["full_name"] = naam
    data["email"] = email
    data["viewing_preference"] = viewing
    if viewing == "video_call":
        data["video_call_number"] = "+31699999999"
    data["study_proof"] = (io.BytesIO(b"fake-pdf-bytes"), "enrollment.pdf")
    client.post("/aanbod/mahoniestraat/1/apply", data=data, content_type="multipart/form-data")


def _login(client):
    client.post("/login", data={"username": "beheerder", "password": "geheim123"})


# --- Losse functies ---


def test_serialiseer_en_parse_aanmelder_round_trip():
    ruw = serialiseer_aanmelder("1", "Jane Doe", "jane@example.com", "+31612345678", "In person", "")
    aanmelder = parse_aanmelder(ruw)
    assert aanmelder == {
        "kamer": "1", "naam": "Jane Doe", "email": "jane@example.com", "telefoon": "+31612345678",
        "bezichtiging": "In person", "videobel_nummer": "",
    }


def test_bel_nummer_video_call_gebruikt_videobelnummer():
    aanmelder = {"telefoon": "+31611111111", "bezichtiging": "Video call", "videobel_nummer": "+31622222222"}
    assert bel_nummer(aanmelder) == "+31622222222"


def test_bel_nummer_in_person_gebruikt_gewone_telefoon():
    aanmelder = {"telefoon": "+31611111111", "bezichtiging": "In person", "videobel_nummer": ""}
    assert bel_nummer(aanmelder) == "+31611111111"


def test_bereken_planning_plant_achter_elkaar():
    aanmelders = [{"naam": "A"}, {"naam": "B"}, {"naam": "C"}]
    afspraken = bereken_planning(aanmelders, time(14, 0), 15)
    assert [(a["tijd_start"], a["tijd_eind"]) for a in afspraken] == [
        ("14:00", "14:15"), ("14:15", "14:30"), ("14:30", "14:45"),
    ]


# --- Routes ---


def test_bezichtiging_formulier_zonder_selectie_geeft_melding(app_client):
    _login(app_client)
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtiging", data={}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "selecteer minstens 1" in resp.get_data(as_text=True).lower()


def test_aanmeldingen_overzicht_heeft_checkboxen_voor_bezichtiging(app_client):
    _login(app_client)
    _dien_aanmelding_in(app_client)
    resp = app_client.get("/pand/mahoniestraat/aanmeldingen")
    body = resp.get_data(as_text=True)
    assert 'name="aanmelders"' in body
    assert "1|Jane Doe|jane@example.com|+31612345678|In person|" in body
    assert "Plan bezichtiging in" in body


def test_volledige_bezichtigingsflow_stuurt_bevestiging_en_overzicht(app_client, verstuurde_mails):
    _login(app_client)
    _dien_aanmelding_in(app_client, naam="Jane Doe", email="jane@example.com", viewing="in_person")
    _dien_aanmelding_in(app_client, naam="John Smith", email="john@example.com", viewing="video_call")
    verstuurde_mails.clear()  # de meldingsmails van de twee aanmeldingen zelf zijn hier niet relevant

    aanmelder_1 = serialiseer_aanmelder("1", "Jane Doe", "jane@example.com", "+31612345678", "In person", "")
    aanmelder_2 = serialiseer_aanmelder(
        "1", "John Smith", "john@example.com", "+31612345678", "Video call", "+31699999999"
    )

    voorstel = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtiging/voorstel",
        data={
            "aanmelders": [aanmelder_1, aanmelder_2],
            "datum": "2026-08-01", "tijd_vanaf": "14:00", "tijd_tot": "15:00", "duur_minuten": "15",
        },
    )
    assert voorstel.status_code == 200
    body = voorstel.get_data(as_text=True)
    assert "14:00 - 14:15" in body
    assert "14:15 - 14:30" in body
    assert "Jane Doe" in body and "John Smith" in body
    assert "+31699999999" in body  # video-bel-nummer van John, niet zijn gewone telefoon

    bevestig = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtiging/bevestigen",
        data={
            "datum": "2026-08-01",
            "afspraken": [
                "1|Jane Doe|jane@example.com|+31612345678|In person||14:00|14:15",
                "1|John Smith|john@example.com|+31612345678|Video call|+31699999999|14:15|14:30",
            ],
        },
        follow_redirects=True,
    )
    assert bevestig.status_code == 200
    assert "2 van 2" in bevestig.get_data(as_text=True)

    # 2 individuele bevestigingsmails + 1 overzichtsmail naar de beheerders
    assert len(verstuurde_mails) == 3
    aan_adressen = [m["aan"] for m in verstuurde_mails]
    assert "jane@example.com" in aan_adressen
    assert "john@example.com" in aan_adressen

    jane_mail = next(m for m in verstuurde_mails if m["aan"] == "jane@example.com")
    assert jane_mail["bcc"] == ["jmmreckman@gmail.com"]  # niet naar alle beheerders
    assert "14:00 - 14:15" in jane_mail["tekst"]
    assert "Mahoniestraat 15" in jane_mail["tekst"]

    john_mail = next(m for m in verstuurde_mails if m["aan"] == "john@example.com")
    assert "video call" in john_mail["tekst"].lower()
    assert "+31699999999" in john_mail["tekst"]

    overzicht_mail = next(m for m in verstuurde_mails if m["aan"] not in ("jane@example.com", "john@example.com"))
    assert "jurian@example.com" in overzicht_mail["aan"]
    assert "justin@example.com" in overzicht_mail["aan"]
    assert "Jane Doe" in overzicht_mail["tekst"]
    assert "John Smith" in overzicht_mail["tekst"]
    assert overzicht_mail["bcc"] == []


def test_bezichtiging_voorstel_met_ongeldige_tijden_toont_foutmelding(app_client):
    _login(app_client)
    _dien_aanmelding_in(app_client)
    aanmelder_1 = serialiseer_aanmelder("1", "Jane Doe", "jane@example.com", "+31612345678", "In person", "")
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtiging/voorstel",
        data={
            "aanmelders": [aanmelder_1],
            "datum": "2026-08-01", "tijd_vanaf": "15:00", "tijd_tot": "14:00", "duur_minuten": "15",
        },
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "eindtijd moet na de begintijd" in body.lower()
    assert 'value="' + aanmelder_1 + '"' in body  # selectie blijft behouden


def test_bezichtiging_bevestigen_zonder_afspraken_redirect(app_client):
    _login(app_client)
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtiging/bevestigen",
        data={"datum": "2026-08-01"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "geen bezichtigingen" in resp.get_data(as_text=True).lower()


def test_bezichtiging_mislukte_mail_telt_mee_in_de_melding(app_client, monkeypatch):
    import webapp.app as appmodule
    from kamerverhuur_scanner.mailer import MailError

    def _falende_mailer(config, aan, onderwerp, tekst, bcc=None, **kwargs):
        if aan == "jane@example.com":
            raise MailError("SMTP tijdelijk niet bereikbaar")

    monkeypatch.setattr(appmodule, "verstuur_email", _falende_mailer)
    _login(app_client)
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtiging/bevestigen",
        data={
            "datum": "2026-08-01",
            "afspraken": ["1|Jane Doe|jane@example.com|+31612345678|In person||14:00|14:15"],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "0 van 1" in body
    assert "mislukt voor" in body.lower()
    assert "jane doe" in body.lower()
