import pytest

from webapp.aanmeldingen import AanmeldingFout, valideer_en_bouw

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
    "income_amount": "€1200",
    "guarantor": "Yes",
    "guarantor_name": "John Doe",
    "guarantor_relation": "Father",
    "guarantor_email": "john@example.com",
    "viewing_preference": "in_person",
    "agree_rules": "on",
}


def test_volledig_formulier_met_bestand_is_geldig():
    aanmelding = valideer_en_bouw(VOLLEDIG_FORMULIER, heeft_bestand=True)
    assert aanmelding.naam == "Jane Doe"
    assert aanmelding.bezichtiging == "In person"
    assert aanmelding.bewijs_inschrijving_link == ""
    assert aanmelding.borgsteller_naam == "John Doe"
    assert aanmelding.borgsteller_relatie == "Father"
    assert aanmelding.borgsteller_email == "john@example.com"


def test_borgsteller_nee_vereist_geen_borgstellergegevens():
    form = {**VOLLEDIG_FORMULIER, "guarantor": "No"}
    del form["guarantor_name"], form["guarantor_relation"], form["guarantor_email"]
    aanmelding = valideer_en_bouw(form, heeft_bestand=True)
    assert aanmelding.borgsteller_naam == ""
    assert aanmelding.borgsteller_relatie == ""
    assert aanmelding.borgsteller_email == ""


def test_borgsteller_ja_zonder_borgstellergegevens_geeft_fout():
    form = dict(VOLLEDIG_FORMULIER)
    del form["guarantor_name"]
    with pytest.raises(AanmeldingFout, match="Guarantor name"):
        valideer_en_bouw(form, heeft_bestand=True)


def test_video_call_vereist_telefoonnummer():
    form = {**VOLLEDIG_FORMULIER, "viewing_preference": "video_call"}
    with pytest.raises(AanmeldingFout):
        valideer_en_bouw(form, heeft_bestand=True)

    form["video_call_number"] = "+31687654321"
    aanmelding = valideer_en_bouw(form, heeft_bestand=True)
    assert aanmelding.bezichtiging == "Video call"
    assert aanmelding.videobel_nummer == "+31687654321"


def test_zonder_bewijs_van_inschrijving_geeft_fout():
    with pytest.raises(AanmeldingFout):
        valideer_en_bouw(VOLLEDIG_FORMULIER, heeft_bestand=False)


def test_zonder_akkoord_huisregels_geeft_fout():
    form = {**VOLLEDIG_FORMULIER, "agree_rules": ""}
    with pytest.raises(AanmeldingFout):
        valideer_en_bouw(form, heeft_bestand=True)


def test_ontbrekend_verplicht_veld_geeft_fout():
    form = dict(VOLLEDIG_FORMULIER)
    del form["email"]
    with pytest.raises(AanmeldingFout, match="Email address"):
        valideer_en_bouw(form, heeft_bestand=True)
