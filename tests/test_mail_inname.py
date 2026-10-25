"""Tests voor de pure delen van de dagelijkse mail-inname (webapp/mail_inname.py):
adressen terugvinden in een (doorgestuurde) mail en de velden parsen. Geen IMAP,
geen netwerk."""
from email.message import EmailMessage

from webapp import mail_inname


def _maak_mail(van, naar, onderwerp, body, cc=None):
    msg = EmailMessage()
    msg["From"] = van
    msg["To"] = naar
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = onderwerp
    msg["Date"] = "Sun, 25 Oct 2026 14:12:00 +0100"
    msg["Message-ID"] = "<test123@steenhub.nl>"
    msg.set_content(body)
    return msg.as_bytes()


def test_adressen_in_mail_directe_afzender_vooraan():
    raw = _maak_mail("Nushka <ndevos1@hotmail.com>", "onderhoud@steenhub.nl",
                     "Lekkage", "De kraan lekt weer.")
    adressen = mail_inname.adressen_in_mail(raw)
    assert adressen[0] == "ndevos1@hotmail.com"
    assert "onderhoud@steenhub.nl" in adressen


def test_adressen_in_mail_vindt_doorgestuurd_huurder_adres_in_body():
    # Jurian stuurt een huurdersmail door: afzender is Jurian, het huurder-adres
    # staat in de geciteerde tekst. Dat moet alsnog gevonden worden.
    body = ("Hoi, zie onderstaande.\n\n"
            "---------- Doorgestuurd bericht ----------\n"
            "Van: Thomas <tmcmorrow02@gmail.com>\n"
            "Datum: 25 okt 2026\n"
            "Aan: jmmreckman@gmail.com\n\n"
            "De verwarming doet het niet.")
    raw = _maak_mail("Jurian <jmmreckman@gmail.com>", "onderhoud@steenhub.nl",
                     "Fwd: verwarming", body)
    adressen = mail_inname.adressen_in_mail(raw)
    assert "tmcmorrow02@gmail.com" in adressen  # het huurder-adres uit de body


def test_parse_inkomend_velden_en_richting_in():
    raw = _maak_mail("Nushka <ndevos1@hotmail.com>", "communicatie@steenhub.nl",
                     "Vraag over de huur", "Wat is mijn huur?")
    g = mail_inname.parse_inkomend(raw)
    assert g["van"] == "ndevos1@hotmail.com"
    assert g["onderwerp"] == "Vraag over de huur"
    assert g["richting"] == "in"
    assert g["message_id"] == "<test123@steenhub.nl>"
    assert g["datum"].startswith("2026-10-25T14:12")
    assert "Wat is mijn huur?" in g["body"]
