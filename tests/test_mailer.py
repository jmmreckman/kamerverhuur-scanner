"""Tests voor het versturen van e-mails (betaalherinnering/ingebrekestelling)."""
from unittest.mock import MagicMock, patch

import pytest

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.mailer import MailError, verstuur_email


def _config(**overrides) -> Config:
    basis = dict(
        google_service_account_file="fake.json", properties_file="properties.json",
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file="users.json", flask_secret_key="test-secret",
        bedrag_tolerantie=1, vooruitbetaling_dagen=14,
        smtp_host="smtp.example.com", smtp_port=587, smtp_username="info@steenhub.nl",
        smtp_password="geheim", smtp_from_email="info@steenhub.nl", smtp_from_naam="Steenhub",
        email_bcc=["eigenaar@example.com", "justin@example.com"],
    )
    basis.update(overrides)
    return Config(**basis)


def test_verstuur_email_zonder_smtp_instellingen_geeft_mailerror():
    config = _config(smtp_host=None)
    with pytest.raises(MailError):
        verstuur_email(config, "huurder@example.com", "Onderwerp", "Tekst")


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_verstuur_email_gebruikt_starttls_en_bcc(mock_smtp_cls):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    config = _config()

    verstuur_email(config, "huurder@example.com", "Betaalherinnering", "Beste Luisa,\n\n...")

    mock_smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=20)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("info@steenhub.nl", "geheim")
    assert smtp_instance.send_message.call_count == 1
    verzonden_bericht = smtp_instance.send_message.call_args[0][0]
    assert verzonden_bericht["To"] == "huurder@example.com"
    assert verzonden_bericht["Bcc"] == "eigenaar@example.com, justin@example.com"
    assert "info@steenhub.nl" in verzonden_bericht["From"]


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_verstuur_email_expliciete_bcc_overschrijft_config(mock_smtp_cls):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    config = _config()  # config.email_bcc = eigenaar + justin

    verstuur_email(config, "huurder@example.com", "Onderwerp", "Tekst", bcc=["alleen-dit-pand@example.com"])

    verzonden_bericht = smtp_instance.send_message.call_args[0][0]
    assert verzonden_bericht["Bcc"] == "alleen-dit-pand@example.com"


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_verstuur_email_lege_bcc_lijst_laat_bcc_header_weg(mock_smtp_cls):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    config = _config()

    verstuur_email(config, "huurder@example.com", "Onderwerp", "Tekst", bcc=[])

    verzonden_bericht = smtp_instance.send_message.call_args[0][0]
    assert verzonden_bericht["Bcc"] is None


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_verstuur_email_zet_reply_to_op_bcc_adressen(mock_smtp_cls):
    # Antwoordt de huurder op de mail, dan moet dat bij de beheerder(s)
    # terechtkomen - niet alleen in de info@-mailbox die niemand dagelijks
    # leest.
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    config = _config()

    verstuur_email(config, "huurder@example.com", "Onderwerp", "Tekst", bcc=["eigenaar@example.com"])

    verzonden_bericht = smtp_instance.send_message.call_args[0][0]
    assert verzonden_bericht["Reply-To"] == "eigenaar@example.com"


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_verstuur_email_zonder_bcc_geen_reply_to(mock_smtp_cls):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    config = _config()

    verstuur_email(config, "huurder@example.com", "Onderwerp", "Tekst", bcc=[])

    verzonden_bericht = smtp_instance.send_message.call_args[0][0]
    assert verzonden_bericht["Reply-To"] is None


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_verstuur_email_met_cc(mock_smtp_cls):
    # CC is (i.t.t. BCC) zichtbaar voor de ontvanger - gebruikt bv. bij het
    # mailen van een concept-huurcontract, waarbij de beheerders bewust
    # zichtbaar meegenomen worden.
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    config = _config()

    verstuur_email(config, "huurder@example.com", "Onderwerp", "Tekst", cc=["jurian@steenhub.nl", "justin@steenhub.nl"])

    verzonden_bericht = smtp_instance.send_message.call_args[0][0]
    assert verzonden_bericht["Cc"] == "jurian@steenhub.nl, justin@steenhub.nl"


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_verstuur_email_zonder_cc_geen_cc_header(mock_smtp_cls):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    config = _config()

    verstuur_email(config, "huurder@example.com", "Onderwerp", "Tekst")

    verzonden_bericht = smtp_instance.send_message.call_args[0][0]
    assert verzonden_bericht["Cc"] is None


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_verstuur_email_met_bijlage(mock_smtp_cls):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    config = _config()

    verstuur_email(
        config, "huurder@example.com", "Onderwerp", "Tekst",
        bijlagen=[("contract.pdf", "application/pdf", b"%PDF-fake-inhoud")],
    )

    verzonden_bericht = smtp_instance.send_message.call_args[0][0]
    bijlagen = list(verzonden_bericht.iter_attachments())
    assert len(bijlagen) == 1
    assert bijlagen[0].get_filename() == "contract.pdf"
    assert bijlagen[0].get_content_type() == "application/pdf"
    assert bijlagen[0].get_content() == b"%PDF-fake-inhoud"


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_verstuur_email_afzender_email_overschrijft_smtp_from_email(mock_smtp_cls):
    # Zodat een ingelogde beheerder met een eigen mailadres (zie
    # webapp/auth.py: User.email) vanaf dat adres verstuurt, i.p.v. altijd
    # het algemene SMTP_FROM_EMAIL - nog steeds met dezelfde SMTP-login.
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    config = _config()

    verstuur_email(config, "huurder@example.com", "Onderwerp", "Tekst", afzender_email="jurian@steenhub.nl")

    mock_smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=20)
    smtp_instance.login.assert_called_once_with("info@steenhub.nl", "geheim")  # zelfde SMTP-login
    verzonden_bericht = smtp_instance.send_message.call_args[0][0]
    assert "jurian@steenhub.nl" in verzonden_bericht["From"]
    assert "info@steenhub.nl" not in verzonden_bericht["From"]


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP")
def test_verstuur_email_zonder_afzender_email_gebruikt_smtp_from_email(mock_smtp_cls):
    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp_instance
    config = _config()

    verstuur_email(config, "huurder@example.com", "Onderwerp", "Tekst")

    verzonden_bericht = smtp_instance.send_message.call_args[0][0]
    assert "info@steenhub.nl" in verzonden_bericht["From"]


@patch("kamerverhuur_scanner.mailer.smtplib.SMTP_SSL")
def test_verstuur_email_gebruikt_ssl_op_poort_465(mock_smtp_ssl_cls):
    smtp_instance = MagicMock()
    mock_smtp_ssl_cls.return_value.__enter__.return_value = smtp_instance
    config = _config(smtp_port=465)

    verstuur_email(config, "huurder@example.com", "Onderwerp", "Tekst")

    mock_smtp_ssl_cls.assert_called_once_with("smtp.example.com", 465, timeout=20)
    smtp_instance.login.assert_called_once()
    smtp_instance.send_message.assert_called_once()
