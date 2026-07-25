from rotterdam_scanner.config import Config, load_config


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


# --- load_config() end-to-end: elk veld moet ook echt uit de omgeving landen in
# de Config, niet alleen als dataclass-veld bestaan (zie ook: de bug in de andere
# steenhub-app waarbij RCLONE_REMOTE nooit daadwerkelijk werd uitgelezen). ---


def _zet_verplichte_env(monkeypatch):
    monkeypatch.setenv("SCANNER_GMAIL_ADDRESS", "scanner@example.com")
    monkeypatch.setenv("SCANNER_GMAIL_APP_PASSWORD", "gmail-pw")


def test_load_config_zonder_kansen_app_users_geeft_lege_dict(monkeypatch, tmp_path):
    _zet_verplichte_env(monkeypatch)
    monkeypatch.delenv("KANSEN_APP_USERS", raising=False)
    config = load_config(tmp_path / "geen-env-bestand")
    assert config.kansen_app_users == {}


def test_load_config_leest_kansen_app_users(monkeypatch, tmp_path):
    _zet_verplichte_env(monkeypatch)
    monkeypatch.setenv("KANSEN_APP_USERS", "jurian:wachtwoord1,justin:wachtwoord2")
    config = load_config(tmp_path / "geen-env-bestand")
    assert config.kansen_app_users == {"jurian": "wachtwoord1", "justin": "wachtwoord2"}


def test_load_config_leest_kansen_app_secret_key(monkeypatch, tmp_path):
    _zet_verplichte_env(monkeypatch)
    monkeypatch.setenv("KANSEN_APP_SECRET_KEY", "test-secret")
    config = load_config(tmp_path / "geen-env-bestand")
    assert config.kansen_app_secret_key == "test-secret"
