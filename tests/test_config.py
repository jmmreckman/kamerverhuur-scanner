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


def test_load_config_zonder_apify_instellingen_geeft_lege_defaults(monkeypatch, tmp_path):
    _zet_verplichte_env(monkeypatch)
    for naam in ["APIFY_API_TOKEN", "APIFY_ACTOR_ID", "APIFY_SEARCH_URLS"]:
        monkeypatch.delenv(naam, raising=False)
    config = load_config(tmp_path / "geen-env-bestand")
    assert config.apify_api_token == ""
    assert config.apify_actor_id == "easyapi/funda-nl-scraper"
    assert config.apify_search_urls == []
    assert config.apify_max_items_dagelijks == 150
    assert config.apify_max_items_wekelijks == 2000


def test_load_config_leest_apify_token_en_actor(monkeypatch, tmp_path):
    _zet_verplichte_env(monkeypatch)
    monkeypatch.setenv("APIFY_API_TOKEN", "apify-token-123")
    monkeypatch.setenv("APIFY_ACTOR_ID", "memo23/funda-scraper")
    config = load_config(tmp_path / "geen-env-bestand")
    assert config.apify_api_token == "apify-token-123"
    assert config.apify_actor_id == "memo23/funda-scraper"


def test_load_config_leest_apify_search_urls_pipe_gescheiden(monkeypatch, tmp_path):
    _zet_verplichte_env(monkeypatch)
    monkeypatch.setenv(
        "APIFY_SEARCH_URLS",
        "https://www.funda.nl/koop/rotterdam/|https://www.funda.nl/koop/hoek-van-holland/",
    )
    config = load_config(tmp_path / "geen-env-bestand")
    assert config.apify_search_urls == [
        "https://www.funda.nl/koop/rotterdam/",
        "https://www.funda.nl/koop/hoek-van-holland/",
    ]


def test_load_config_leest_apify_max_items(monkeypatch, tmp_path):
    _zet_verplichte_env(monkeypatch)
    monkeypatch.setenv("APIFY_MAX_ITEMS_DAGELIJKS", "80")
    monkeypatch.setenv("APIFY_MAX_ITEMS_WEKELIJKS", "3000")
    config = load_config(tmp_path / "geen-env-bestand")
    assert config.apify_max_items_dagelijks == 80
    assert config.apify_max_items_wekelijks == 3000
