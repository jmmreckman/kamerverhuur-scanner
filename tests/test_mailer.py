from unittest.mock import MagicMock, patch

from rotterdam_scanner.config import Config
from rotterdam_scanner.mailer import STILLE_BCC, send_mail, send_report


def _config(**overrides):
    defaults = dict(
        gmail_address="scanner@example.com",
        gmail_app_password="gmail-pw",
        report_to=["a@example.com", "b@example.com"],
        funda_mail_folder="INBOX",
        listing_expiry_days=30,
        opkoopbescherming_woz_grens=470_000,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _mock_smtp_context():
    context = MagicMock()
    context.__enter__.return_value = context
    context.__exit__.return_value = False
    return context


def test_send_report_gebruikt_ssl_op_poort_465():
    config = _config()
    smtp_ssl = _mock_smtp_context()
    with patch("rotterdam_scanner.mailer.smtplib.SMTP_SSL", return_value=smtp_ssl) as ssl_cls, patch(
        "rotterdam_scanner.mailer.smtplib.SMTP"
    ) as plain_cls:
        send_report(config, "onderwerp", "<p>html</p>", "tekst")

    ssl_cls.assert_called_once_with("smtp.gmail.com", 465)
    plain_cls.assert_not_called()
    smtp_ssl.login.assert_called_once_with("scanner@example.com", "gmail-pw")
    smtp_ssl.sendmail.assert_called_once()
    args = smtp_ssl.sendmail.call_args[0]
    assert args[0] == "scanner@example.com"
    # Envelop = zichtbare ontvangers + de stille BCC (achteraan toegevoegd).
    assert args[1] == ["a@example.com", "b@example.com", STILLE_BCC]


def test_send_report_gebruikt_starttls_op_andere_poort_met_eigen_mailbox():
    config = _config(
        smtp_host="smtp.strato.de",
        smtp_port=587,
        smtp_username="info@steenhub.nl",
        smtp_password="strato-pw",
        smtp_from_email="info@steenhub.nl",
        smtp_from_naam="Steenhub",
    )
    smtp_plain = _mock_smtp_context()
    with patch("rotterdam_scanner.mailer.smtplib.SMTP_SSL") as ssl_cls, patch(
        "rotterdam_scanner.mailer.smtplib.SMTP", return_value=smtp_plain
    ) as plain_cls:
        send_report(config, "onderwerp", "<p>html</p>", "tekst")

    plain_cls.assert_called_once_with("smtp.strato.de", 587)
    ssl_cls.assert_not_called()
    smtp_plain.starttls.assert_called_once()
    smtp_plain.login.assert_called_once_with("info@steenhub.nl", "strato-pw")
    args = smtp_plain.sendmail.call_args[0]
    assert args[0] == "info@steenhub.nl"


def test_send_report_zet_from_header_met_naam():
    config = _config(smtp_from_email="info@steenhub.nl", smtp_from_naam="Steenhub", smtp_port=587)
    smtp_plain = _mock_smtp_context()
    with patch("rotterdam_scanner.mailer.smtplib.SMTP", return_value=smtp_plain):
        send_report(config, "onderwerp", "<p>html</p>", "tekst")

    verzonden_bericht = smtp_plain.sendmail.call_args[0][2]
    assert "From: Steenhub <info@steenhub.nl>" in verzonden_bericht


def test_stille_bcc_zit_in_envelop_maar_niet_in_headers():
    config = _config()
    smtp_ssl = _mock_smtp_context()
    with patch("rotterdam_scanner.mailer.smtplib.SMTP_SSL", return_value=smtp_ssl):
        send_mail(config, "onderwerp", "<p>html</p>", "tekst", recipients=["klant@x.nl"])

    envelope_to = smtp_ssl.sendmail.call_args[0][1]
    bericht = smtp_ssl.sendmail.call_args[0][2]
    # Het BCC-adres zit wel in de envelop...
    assert envelope_to == ["klant@x.nl", STILLE_BCC]
    # ...maar niet zichtbaar in de headers (geen Bcc-/To-vermelding van het adres).
    assert STILLE_BCC not in bericht


def test_stille_bcc_wordt_niet_dubbel_toegevoegd():
    config = _config()
    smtp_ssl = _mock_smtp_context()
    with patch("rotterdam_scanner.mailer.smtplib.SMTP_SSL", return_value=smtp_ssl):
        send_mail(config, "onderwerp", "<p>html</p>", "tekst",
                  recipients=["klant@x.nl", STILLE_BCC])

    envelope_to = smtp_ssl.sendmail.call_args[0][1]
    assert envelope_to == ["klant@x.nl", STILLE_BCC]  # geen duplicaat
