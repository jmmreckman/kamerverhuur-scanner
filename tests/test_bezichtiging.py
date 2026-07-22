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


# --- Bezichtigers toevoegen aan een bestaande lijst ---


def _bevestig(client, datum, afspraken):
    return client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtiging/bevestigen",
        data={"datum": datum, "afspraken": afspraken},
    )


def test_toevoegen_zonder_bestaande_lijst_geeft_melding(app_client):
    _login(app_client)
    _dien_aanmelding_in(app_client)
    aanmelder_1 = serialiseer_aanmelder("1", "Jane Doe", "jane@example.com", "+31612345678", "In person", "")
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtiging/toevoegen",
        data={"aanmelders": [aanmelder_1]}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "nog geen eerdere bezichtigingslijst" in resp.get_data(as_text=True).lower()


def test_toevoegen_met_1_bestaande_lijst_gaat_direct_door_en_sluit_aan(app_client):
    _login(app_client)
    _dien_aanmelding_in(app_client, naam="Jane Doe", email="jane@example.com")
    _bevestig(app_client, "2026-08-01", ["1|Jane Doe|jane@example.com|+31612345678|In person||14:00|14:15"])

    aanmelder_2 = serialiseer_aanmelder("1", "New Guy", "newguy@example.com", "+31611111111", "In person", "")
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtiging/toevoegen",
        data={"aanmelders": [aanmelder_2]},
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "wordt toegevoegd aan de bestaande lijst van 2026-08-01" in body.lower()
    assert 'name="tijd_vanaf" value="14:15"' in body  # sluit aan op het bestaande laatste tijdslot
    assert 'name="duur_minuten" value="15"' in body  # duur afgeleid van de laatste bestaande afspraak
    assert 'value="2026-08-01"' in body


def test_toevoegen_met_meerdere_lijsten_toont_kiezer(app_client):
    _login(app_client)
    _dien_aanmelding_in(app_client, naam="Jane Doe", email="jane@example.com")
    _bevestig(app_client, "2026-08-01", ["1|Jane Doe|jane@example.com|+31612345678|In person||14:00|14:15"])
    _bevestig(app_client, "2026-08-05", ["1|Jane Doe|jane@example.com|+31612345678|In person||10:00|10:15"])

    aanmelder_2 = serialiseer_aanmelder("1", "New Guy", "newguy@example.com", "+31611111111", "In person", "")
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtiging/toevoegen",
        data={"aanmelders": [aanmelder_2]},
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-08-01" in body and "2026-08-05" in body
    assert "kies een bestaande lijst" in body.lower()

    kies = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtiging/toevoegen/kies",
        data={"aanmelders": [aanmelder_2], "datum": "2026-08-05"},
    )
    assert kies.status_code == 200
    kies_body = kies.get_data(as_text=True)
    assert 'name="tijd_vanaf" value="10:15"' in kies_body
    assert 'value="2026-08-05"' in kies_body


def test_toevoegen_flow_persisteert_en_overzichtsmail_bevat_oude_en_nieuwe(app_client, verstuurde_mails):
    _login(app_client)
    _dien_aanmelding_in(app_client, naam="Jane Doe", email="jane@example.com")
    verstuurde_mails.clear()
    _bevestig(app_client, "2026-08-01", ["1|Jane Doe|jane@example.com|+31612345678|In person||14:00|14:15"])
    verstuurde_mails.clear()

    _bevestig(
        app_client, "2026-08-01",
        ["1|New Guy|newguy@example.com|+31611111111|In person||14:15|14:30"],
    )

    sheet = _fake_sheet_singleton["mahoniestraat"]
    assert len(sheet.bezichtigingen) == 2
    assert {a["naam"] for _d, a in sheet.bezichtigingen} == {"Jane Doe", "New Guy"}

    overzicht_mail = next(m for m in verstuurde_mails if m["aan"] not in ("newguy@example.com",))
    assert "Jane Doe" in overzicht_mail["tekst"]  # de eerder al bevestigde afspraak staat er nog steeds in
    assert "New Guy" in overzicht_mail["tekst"]


# --- "Ingepland"-indicator op de aanmeldingenpagina ---


def test_aanmeldingen_overzicht_toont_ingepland_indicator(app_client):
    _login(app_client)
    _dien_aanmelding_in(app_client, naam="Jane Doe", email="jane@example.com")
    _dien_aanmelding_in(app_client, naam="John Smith", email="john@example.com")
    _bevestig(app_client, "2026-08-01", ["1|Jane Doe|jane@example.com|+31612345678|In person||14:00|14:15"])

    resp = app_client.get("/pand/mahoniestraat/aanmeldingen")
    body = resp.get_data(as_text=True)
    assert body.count("✓ Ingepland") == 1  # alleen bij Jane Doe, niet bij John Smith


# --- Bezichtigingen-overzicht + verwijderen ---


def test_bezichtigingen_overzicht_toont_ingeplande_afspraken(app_client):
    _login(app_client)
    _dien_aanmelding_in(app_client, naam="Jane Doe", email="jane@example.com")
    _bevestig(app_client, "2026-08-01", ["1|Jane Doe|jane@example.com|+31612345678|In person||14:00|14:15"])

    resp = app_client.get("/pand/mahoniestraat/aanmeldingen/bezichtigingen")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Jane Doe" in body
    assert "14:00" in body and "14:15" in body


def test_bezichtigingen_overzicht_leeg(app_client):
    _login(app_client)
    resp = app_client.get("/pand/mahoniestraat/aanmeldingen/bezichtigingen")
    assert resp.status_code == 200
    assert "nog geen bezichtigingen" in resp.get_data(as_text=True).lower()


def test_bezichtigingen_verwijderen_maakt_tijdslot_weer_vrij(app_client):
    _login(app_client)
    _dien_aanmelding_in(app_client, naam="Jane Doe", email="jane@example.com")
    _bevestig(app_client, "2026-08-01", ["1|Jane Doe|jane@example.com|+31612345678|In person||14:00|14:15"])
    _bevestig(app_client, "2026-08-01", ["1|John Smith|john@example.com|+31611111111|In person||14:15|14:30"])

    sheet = _fake_sheet_singleton["mahoniestraat"]
    rijnummer_jane = sheet.get_bezichtigingen_met_rijnummer()[0][0]

    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtigingen/verwijderen",
        data={"rijnummers": [str(rijnummer_jane)]}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "1 bezichtiging(en) verwijderd" in resp.get_data(as_text=True)

    overgebleven = sheet.get_bezichtigingen()
    assert len(overgebleven) == 1
    assert overgebleven[0][4] == "John Smith"


def test_bezichtigingen_verwijderen_zonder_selectie_geeft_melding(app_client):
    _login(app_client)
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/bezichtigingen/verwijderen", data={}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "selecteer minstens 1" in resp.get_data(as_text=True).lower()


# --- Afwijzing sturen ---


def test_afwijzing_formulier_toont_standaardtekst_en_ontvangers(app_client):
    _login(app_client)
    _dien_aanmelding_in(app_client, naam="Jane Doe", email="jane@example.com")
    aanmelder = serialiseer_aanmelder("1", "Jane Doe", "jane@example.com", "+31612345678", "In person", "")
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/afwijzen", data={"aanmelders": [aanmelder]},
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Jane Doe" in body
    assert "reserve list" in body.lower()
    assert "Mahoniestraat 15" in body


def test_afwijzing_versturen_mailt_iedereen_apart_met_beheerder_only_bcc(app_client, verstuurde_mails):
    _login(app_client)
    aanmelder_1 = serialiseer_aanmelder("1", "Jane Doe", "jane@example.com", "+31612345678", "In person", "")
    aanmelder_2 = serialiseer_aanmelder("1", "John Smith", "john@example.com", "+31611111111", "In person", "")

    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/afwijzen/versturen",
        data={
            "aanmelders": [aanmelder_1, aanmelder_2],
            "onderwerp": "Update on your application - Mahoniestraat 15",
            "tekst": "Dear applicant, thanks but no thanks - reserve list.",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "2 van 2" in resp.get_data(as_text=True)

    assert len(verstuurde_mails) == 2
    aan_adressen = {m["aan"] for m in verstuurde_mails}
    assert aan_adressen == {"jane@example.com", "john@example.com"}
    for mail in verstuurde_mails:
        assert mail["bcc"] == ["jmmreckman@gmail.com"]  # niet naar alle beheerders


def test_afwijzing_versturen_zonder_selectie_redirect(app_client):
    _login(app_client)
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/afwijzen/versturen",
        data={"onderwerp": "Update", "tekst": "Tekst"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "selecteer minstens 1" in resp.get_data(as_text=True).lower()


def test_afwijzing_versturen_mislukte_mail_telt_mee(app_client, monkeypatch):
    import webapp.app as appmodule
    from kamerverhuur_scanner.mailer import MailError

    def _falende_mailer(config, aan, onderwerp, tekst, bcc=None, **kwargs):
        raise MailError("SMTP tijdelijk niet bereikbaar")

    monkeypatch.setattr(appmodule, "verstuur_email", _falende_mailer)
    _login(app_client)
    aanmelder = serialiseer_aanmelder("1", "Jane Doe", "jane@example.com", "+31612345678", "In person", "")
    resp = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/afwijzen/versturen",
        data={"aanmelders": [aanmelder], "onderwerp": "Update", "tekst": "Tekst"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "0 van 1" in body
    assert "mislukt voor" in body.lower()


# --- Licht huurders in ---


def test_licht_huurders_in_zonder_bezichtiging_geeft_melding(app_client):
    _login(app_client)
    resp = app_client.get("/pand/mahoniestraat/aanmeldingen/huurders-inlichten", follow_redirects=True)
    assert resp.status_code == 200
    assert "nog geen bezichtiging ingepland" in resp.get_data(as_text=True).lower()


def test_licht_huurders_in_met_1_datum_redirect_naar_voorgevulde_mail(app_client):
    _login(app_client)
    _dien_aanmelding_in(app_client, naam="Jane Doe", email="jane@example.com")
    _bevestig(app_client, "2026-08-01", ["1|Jane Doe|jane@example.com|+31612345678|In person||14:00|14:15"])
    _bevestig(app_client, "2026-08-01", ["1|John Smith|john@example.com|+31611111111|In person||14:15|14:30"])

    resp = app_client.get("/pand/mahoniestraat/aanmeldingen/huurders-inlichten", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "01-08-2026" in body
    assert "14:00" in body and "14:30" in body
    assert "won&#39;t come into your room" in body or "won't come into your room" in body
    assert "common areas" in body


def test_licht_huurders_in_met_meerdere_datums_toont_kiezer(app_client):
    _login(app_client)
    _dien_aanmelding_in(app_client, naam="Jane Doe", email="jane@example.com")
    _bevestig(app_client, "2026-08-01", ["1|Jane Doe|jane@example.com|+31612345678|In person||14:00|14:15"])
    _bevestig(app_client, "2026-08-05", ["1|Jane Doe|jane@example.com|+31612345678|In person||10:00|10:15"])

    resp = app_client.get("/pand/mahoniestraat/aanmeldingen/huurders-inlichten")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-08-01" in body and "2026-08-05" in body

    kies = app_client.post(
        "/pand/mahoniestraat/aanmeldingen/huurders-inlichten/kies", data={"datum": "2026-08-05"},
        follow_redirects=True,
    )
    assert kies.status_code == 200
    kies_body = kies.get_data(as_text=True)
    assert "05-08-2026" in kies_body
    assert "10:00" in kies_body and "10:15" in kies_body
