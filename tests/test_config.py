from rotterdam_scanner.config import Config


def _config(**overrides):
    defaults = dict(
        gmail_address="scanner@example.com",
        gmail_app_password="gmail-pw",
        report_to=["a@example.com"],
        funda_mail_folder="INBOX",
        listing_expiry_days=30,
        opkoopbescherming_woz_grens=470_000,
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_zonder_smtp_overrides_valt_terug_op_gmail():
    config = _config()
    assert config.effective_smtp_username == "scanner@example.com"
    assert config.effective_smtp_password == "gmail-pw"
    assert config.effective_from_email == "scanner@example.com"
    assert config.effective_from_header == "scanner@example.com"


def test_met_smtp_overrides_gebruikt_eigen_mailbox():
    config = _config(
        smtp_host="smtp.strato.de",
        smtp_port=587,
        smtp_username="info@steenhub.nl",
        smtp_password="strato-pw",
        smtp_from_email="info@steenhub.nl",
        smtp_from_naam="Steenhub",
    )
    assert config.effective_smtp_username == "info@steenhub.nl"
    assert config.effective_smtp_password == "strato-pw"
    assert config.effective_from_email == "info@steenhub.nl"
    assert config.effective_from_header == "Steenhub <info@steenhub.nl>"


def test_imap_blijft_altijd_gmail_ongeacht_smtp_overrides():
    config = _config(smtp_host="smtp.strato.de", smtp_username="info@steenhub.nl")
    assert config.imap_host == "imap.gmail.com"
