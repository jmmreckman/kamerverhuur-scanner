"""Tests voor het AI-sparpaneel (genereer_reactie) - de echte Anthropic API
wordt hier nooit aangeroepen, alleen een nep-client."""
from types import SimpleNamespace

import pytest

from kamerverhuur_scanner import ai_client
from kamerverhuur_scanner.ai_client import AIError, genereer_reactie
from kamerverhuur_scanner.config import Config


def _config(**overrides) -> Config:
    basis = dict(
        google_service_account_file="fake.json", properties_file="properties.json",
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file="users.json", flask_secret_key="test-secret",
        bedrag_tolerantie=__import__("decimal").Decimal("0.01"), vooruitbetaling_dagen=14,
        anthropic_api_key="sk-ant-test", anthropic_model="claude-sonnet-5",
    )
    basis.update(overrides)
    return Config(**basis)


class _FakeMessages:
    def __init__(self, antwoord_tekst, opgevangen):
        self._antwoord_tekst = antwoord_tekst
        self._opgevangen = opgevangen

    def create(self, **kwargs):
        self._opgevangen.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._antwoord_tekst)])


class _FakeAnthropic:
    def __init__(self, antwoord_tekst="Dit is het AI-antwoord.", opgevangen=None):
        self.messages = _FakeMessages(antwoord_tekst, opgevangen if opgevangen is not None else [])


def test_genereer_reactie_zonder_api_key_geeft_aierror():
    with pytest.raises(AIError, match="ANTHROPIC_API_KEY"):
        genereer_reactie(_config(anthropic_api_key=None), "profiel", "", [{"role": "user", "content": "hoi"}])


def test_genereer_reactie_zonder_chatgeschiedenis_geeft_aierror():
    with pytest.raises(AIError):
        genereer_reactie(_config(), "profiel", "", [])


def test_genereer_reactie_geeft_tekst_terug(monkeypatch):
    opgevangen = []
    monkeypatch.setattr(ai_client.anthropic, "Anthropic", lambda api_key: _FakeAnthropic("Bedankt voor uw bericht.", opgevangen))

    antwoord = genereer_reactie(
        _config(), "Emotionele huurder, kort en zakelijk blijven.", "eerdere communicatie hier",
        [{"role": "user", "content": "De huurder klaagt over de verwarming."}],
    )

    assert antwoord == "Bedankt voor uw bericht."
    assert len(opgevangen) == 1
    kwargs = opgevangen[0]
    assert kwargs["model"] == "claude-sonnet-5"
    assert "Emotionele huurder" in kwargs["system"]
    assert "eerdere communicatie hier" in kwargs["system"]
    assert kwargs["messages"] == [{"role": "user", "content": "De huurder klaagt over de verwarming."}]


def test_genereer_reactie_zet_apierror_om_naar_aierror(monkeypatch):
    import anthropic as anthropic_sdk

    class _FalendeMessages:
        def create(self, **kwargs):
            raise anthropic_sdk.APIConnectionError(request=SimpleNamespace())

    monkeypatch.setattr(
        ai_client.anthropic, "Anthropic", lambda api_key: SimpleNamespace(messages=_FalendeMessages())
    )

    with pytest.raises(AIError, match="mislukt"):
        genereer_reactie(_config(), "profiel", "", [{"role": "user", "content": "hoi"}])
