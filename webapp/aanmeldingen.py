"""Verwerkt het publieke aanmeldformulier (reacties op een kameraanbod op de
aanbodpagina). De site is voor de aanmelders in het Engels, vandaar Engelse
foutmeldingen hier."""
from __future__ import annotations

from kamerverhuur_scanner.models import Aanmelding

VEREISTE_VELDEN = {
    "full_name": "Full name",
    "email": "Email address",
    "phone": "Phone number",
    "current_address": "Current address",
    "study_program": "Study programme",
    "student_number": "Student number",
    "desired_start_date": "Desired start date",
    "desired_contract_duration": "Desired contract duration",
    "income_source": "Source of income",
    "income_amount": "Monthly income",
    "guarantor": "Guarantor",
    "viewing_preference": "Viewing preference",
}


class AanmeldingFout(ValueError):
    pass


def valideer_en_bouw(form, heeft_bestand: bool) -> Aanmelding:
    """Valideert het formulier en bouwt een Aanmelding op (zonder de link naar
    het geuploade bewijs - die wordt er na de Drive-upload aan toegevoegd)."""
    ontbrekend = [label for veld, label in VEREISTE_VELDEN.items() if not form.get(veld, "").strip()]
    if form.get("viewing_preference") == "video_call" and not form.get("video_call_number", "").strip():
        ontbrekend.append("Video call phone number")
    if form.get("agree_rules") != "on":
        ontbrekend.append("Agreement to the house rules")
    if not heeft_bestand:
        ontbrekend.append("Proof of study enrollment")
    if ontbrekend:
        raise AanmeldingFout("Please fill in: " + ", ".join(ontbrekend) + ".")

    return Aanmelding(
        naam=form["full_name"].strip(),
        email=form["email"].strip(),
        telefoon=form["phone"].strip(),
        huidig_adres=form["current_address"].strip(),
        studie=form["study_program"].strip(),
        studentnummer=form["student_number"].strip(),
        gewenste_ingangsdatum=form["desired_start_date"].strip(),
        gewenste_huurduur=form["desired_contract_duration"].strip(),
        inkomstenbron=form["income_source"].strip(),
        inkomsten_bedrag=form["income_amount"].strip(),
        borgsteller=form["guarantor"].strip(),
        bezichtiging="Video call" if form.get("viewing_preference") == "video_call" else "In person",
        videobel_nummer=form.get("video_call_number", "").strip(),
        bewijs_inschrijving_link="",
    )
