"""Tests voor het AI-uitlezen van geuploade documenten (ID/paspoort, bewijs
van inkomen/inschrijving) - de echte Anthropic API wordt hier nooit
aangeroepen, alleen een nep-client."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from kamerverhuur_scanner import document_ai
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.document_ai import DocumentAIError, lees_documenten_uit, vergelijk_met_aanmelding


def _config(**overrides) -> Config:
    basis = dict(
        google_service_account_file="fake.json", properties_file="properties.json",
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file="users.json", flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14,
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
    def __init__(self, antwoord_tekst, opgevangen=None):
        self.messages = _FakeMessages(antwoord_tekst, opgevangen if opgevangen is not None else [])


_GELDIG_ANTWOORD = (
    '{"volledige_naam": "Jane Doe", "geboortedatum": "01-01-2000", '
    '"geboorteplaats": "Rotterdam", "studierichting": "Computer Science", "studentnummer": "123456"}'
)


def test_lees_documenten_uit_zonder_api_key_geeft_error():
    with pytest.raises(DocumentAIError, match="ANTHROPIC_API_KEY"):
        lees_documenten_uit(_config(anthropic_api_key=None), [("id.jpg", "image/jpeg", b"fake")])


def test_lees_documenten_uit_zonder_documenten_geeft_error():
    with pytest.raises(DocumentAIError):
        lees_documenten_uit(_config(), [])


def test_lees_documenten_uit_zonder_ondersteund_bestandstype_geeft_error():
    with pytest.raises(DocumentAIError, match="ondersteunde"):
        lees_documenten_uit(_config(), [("id.docx", "application/msword", b"fake")])


def test_lees_documenten_uit_geeft_geparsede_velden_terug(monkeypatch):
    opgevangen = []
    monkeypatch.setattr(
        document_ai.anthropic, "Anthropic", lambda api_key: _FakeAnthropic(_GELDIG_ANTWOORD, opgevangen)
    )

    resultaat = lees_documenten_uit(_config(), [("id.jpg", "image/jpeg", b"fake-id-bytes")])

    assert resultaat == {
        "volledige_naam": "Jane Doe", "geboortedatum": "01-01-2000", "geboorteplaats": "Rotterdam",
        "studierichting": "Computer Science", "studentnummer": "123456",
    }
    assert len(opgevangen) == 1
    kwargs = opgevangen[0]
    assert kwargs["model"] == "claude-sonnet-5"
    content = kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"


def test_lees_documenten_uit_stuurt_pdf_als_document_block(monkeypatch):
    opgevangen = []
    monkeypatch.setattr(
        document_ai.anthropic, "Anthropic", lambda api_key: _FakeAnthropic(_GELDIG_ANTWOORD, opgevangen)
    )

    lees_documenten_uit(_config(), [("loon.pdf", "application/pdf", b"fake-pdf-bytes")])

    content = opgevangen[0]["messages"][0]["content"]
    assert content[0]["type"] == "document"
    assert content[0]["source"]["media_type"] == "application/pdf"


def test_lees_documenten_uit_negeert_niet_ondersteunde_bestanden_tussen_geldige(monkeypatch):
    opgevangen = []
    monkeypatch.setattr(
        document_ai.anthropic, "Anthropic", lambda api_key: _FakeAnthropic(_GELDIG_ANTWOORD, opgevangen)
    )

    lees_documenten_uit(_config(), [
        ("id.jpg", "image/jpeg", b"fake-id-bytes"),
        ("iets.docx", "application/msword", b"onbruikbaar"),
    ])

    content = opgevangen[0]["messages"][0]["content"]
    # alleen het jpeg-bestand (+ het bijbehorende tekstlabel) is meegestuurd
    assert len(content) == 2
    assert content[0]["type"] == "image"


def test_lees_documenten_uit_haalt_markdown_codeblok_eraf(monkeypatch):
    monkeypatch.setattr(
        document_ai.anthropic, "Anthropic",
        lambda api_key: _FakeAnthropic(f"```json\n{_GELDIG_ANTWOORD}\n```"),
    )

    resultaat = lees_documenten_uit(_config(), [("id.jpg", "image/jpeg", b"fake")])
    assert resultaat["volledige_naam"] == "Jane Doe"


def test_lees_documenten_uit_ongeldige_json_geeft_error(monkeypatch):
    monkeypatch.setattr(
        document_ai.anthropic, "Anthropic", lambda api_key: _FakeAnthropic("dit is geen JSON")
    )

    with pytest.raises(DocumentAIError):
        lees_documenten_uit(_config(), [("id.jpg", "image/jpeg", b"fake")])


def test_lees_documenten_uit_zet_apierror_om(monkeypatch):
    import anthropic as anthropic_sdk

    class _FalendeMessages:
        def create(self, **kwargs):
            raise anthropic_sdk.APIConnectionError(request=SimpleNamespace())

    monkeypatch.setattr(
        document_ai.anthropic, "Anthropic",
        lambda api_key: SimpleNamespace(messages=_FalendeMessages()),
    )

    with pytest.raises(DocumentAIError, match="mislukt"):
        lees_documenten_uit(_config(), [("id.jpg", "image/jpeg", b"fake")])


# --- vergelijk_met_aanmelding() ---


def test_vergelijk_met_aanmelding_zonder_afwijkingen_geeft_lege_lijst():
    ai_resultaat = {"volledige_naam": "Jane Doe", "studentnummer": "123456", "studierichting": "Computer Science"}
    assert vergelijk_met_aanmelding(ai_resultaat, "Jane Doe", "Computer Science", "123456") == []


def test_vergelijk_met_aanmelding_signaleert_afwijkende_naam():
    ai_resultaat = {"volledige_naam": "John Doe"}
    mismatches = vergelijk_met_aanmelding(ai_resultaat, "Jane Doe", "", "")
    assert len(mismatches) == 1
    assert "John Doe" in mismatches[0]
    assert "Jane Doe" in mismatches[0]


def test_vergelijk_met_aanmelding_signaleert_afwijkend_studentnummer():
    ai_resultaat = {"studentnummer": "999999"}
    mismatches = vergelijk_met_aanmelding(ai_resultaat, "", "", "123456")
    assert len(mismatches) == 1
    assert "999999" in mismatches[0]


def test_vergelijk_met_aanmelding_signaleert_afwijkende_studierichting():
    ai_resultaat = {"studierichting": "Physics"}
    mismatches = vergelijk_met_aanmelding(ai_resultaat, "", "Computer Science", "")
    assert len(mismatches) == 1


def test_vergelijk_met_aanmelding_negeert_hoofdlettergebruik_bij_naam():
    ai_resultaat = {"volledige_naam": "jane doe"}
    assert vergelijk_met_aanmelding(ai_resultaat, "Jane Doe", "", "") == []


def test_vergelijk_met_aanmelding_zonder_ai_of_aanmeldingswaarde_geeft_geen_mismatch():
    assert vergelijk_met_aanmelding({}, "Jane Doe", "Computer Science", "123456") == []
    assert vergelijk_met_aanmelding({"volledige_naam": "Jane Doe"}, "", "", "") == []
