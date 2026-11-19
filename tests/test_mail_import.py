"""Tests voor de pure delen van webapp/mail_import.py (adres/parse/criteria).
De IMAP-/netwerkdelen worden hier niet getest."""
from email.message import EmailMessage

from webapp import mail_import as mi


def _mail(van, naar, onderwerp, body, *, html=None, message_id="<a@b>", datum="Mon, 05 May 2025 10:00:00 +0200"):
    m = EmailMessage()
    m["From"] = van
    m["To"] = naar
    m["Subject"] = onderwerp
    m["Date"] = datum
    m["Message-ID"] = message_id
    m.set_content(body)
    if html is not None:
        m.add_alternative(html, subtype="html")
    return m.as_bytes()


def test_adres_uit():
    assert mi.adres_uit("Jane Doe <Jane@Example.com>") == "jane@example.com"
    assert mi.adres_uit("plain@x.nl") == "plain@x.nl"
    assert mi.adres_uit(None) == ""


def test_imap_zoek_criteria():
    assert mi.imap_zoek_criteria("x@y.nl") == ["OR", "FROM", "x@y.nl", "TO", "x@y.nl"]


def test_parse_email_ontvangen_van_huurder():
    raw = _mail("ndevos1@hotmail.com", "jmmreckman@gmail.com", "Kraan lekt", "De kraan lekt al dagen.")
    p = mi.parse_email(raw, eigen_adres="jmmreckman@gmail.com")
    assert p["van"] == "ndevos1@hotmail.com"
    assert p["naar"] == "jmmreckman@gmail.com"
    assert p["onderwerp"] == "Kraan lekt"
    assert "kraan lekt" in p["body"].lower()
    assert p["message_id"] == "<a@b>"
    assert p["datum"].startswith("2025-05-05")
    assert p["richting"] == "in"  # huurder is afzender


def test_parse_email_verzonden_door_beheerder():
    raw = _mail("jmmreckman@gmail.com", "ndevos1@hotmail.com", "Re: Kraan", "Ik stuur de loodgieter.")
    p = mi.parse_email(raw, eigen_adres="jmmreckman@gmail.com")
    assert p["richting"] == "uit"  # beheerder is afzender


def test_parse_email_onderwerp_met_encoding():
    raw = _mail("a@b.nl", "c@d.nl", "=?utf-8?q?Vraag_over_de_w=C3=A9k?=", "x")
    p = mi.parse_email(raw, eigen_adres="c@d.nl")
    assert "wék" in p["onderwerp"]


def test_kies_tekst_prefereert_plain_boven_html():
    import email
    raw = _mail("a@b.nl", "c@d.nl", "x", "PLATTE tekst hier", html="<p>HTML tekst</p>")
    msg = email.message_from_bytes(raw)
    assert mi.kies_tekst(msg) == "PLATTE tekst hier"
