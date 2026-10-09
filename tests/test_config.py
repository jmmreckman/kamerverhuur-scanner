"""Tests voor Config.load() - vooral om te borgen dat elk optioneel veld op
de dataclass ook daadwerkelijk uit zijn omgevingsvariabele gelezen wordt.
Regressietest: rclone_remote stond wel als veld op Config, maar werd nooit
in load() ingevuld, waardoor RCLONE_REMOTE in de praktijk altijd genegeerd
werd ondanks een correct ingestelde omgevingsvariabele."""
from kamerverhuur_scanner.config import Config


def _zet_verplichte_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "fake.json")
    monkeypatch.setenv("BUNQ_CONF_FILE", "fake.conf")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")


def test_load_zonder_rclone_remote_geeft_none(monkeypatch):
    _zet_verplichte_env(monkeypatch)
    monkeypatch.delenv("RCLONE_REMOTE", raising=False)
    assert Config.load().rclone_remote is None


def test_load_leest_rclone_remote_uit_omgevingsvariabele(monkeypatch):
    _zet_verplichte_env(monkeypatch)
    monkeypatch.setenv("RCLONE_REMOTE", "gdrive:Vastgoed")
    assert Config.load().rclone_remote == "gdrive:Vastgoed"


def test_load_leest_anthropic_api_key(monkeypatch):
    _zet_verplichte_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert Config.load().anthropic_api_key == "sk-ant-test"
