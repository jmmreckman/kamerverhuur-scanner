"""Tests voor de 'alles betaald'-melding die run_check() eenmalig per pand
per maand naar de beheerder(s) stuurt zodra alle kamers "Betaald" staan."""
from datetime import date
from decimal import Decimal

import pytest

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Pand, Payment, Tenant
from kamerverhuur_scanner.runner import run_check
import kamerverhuur_scanner.runner as runner


def _pand(**overrides) -> Pand:
    basis = dict(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="x",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        bunq_rekening_iban="NL91ABNA0417164300",
    )
    basis.update(overrides)
    return Pand(**basis)


def _config(tmp_path, **overrides) -> Config:
    basis = dict(
        google_service_account_file="fake.json", properties_file="properties.json",
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file="users.json", flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14,
        state_dir=str(tmp_path),
        smtp_host="smtp.example.com", smtp_port=587, smtp_username="info@steenhub.nl",
        smtp_password="geheim", smtp_from_email="info@steenhub.nl", smtp_from_naam="Steenhub",
        email_bcc=["eigenaar@example.com"],
    )
    basis.update(overrides)
    return Config(**basis)


class FakeSheetClient:
    def __init__(self, _config, _pand, tenants=None):
        self._tenants = tenants if tenants is not None else [
            Tenant(row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00")),
        ]
        self.write_results_calls = []
        self.upsert_calls = []

    def get_tenants(self):
        return self._tenants

    def get_geschiedenis(self, kamer):
        return []

    def write_results(self, results):
        self.write_results_calls.append(results)

    def upsert_history(self, results, maand):
        self.upsert_calls.append((maand, results))


class FakeBunqClient:
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        return [
            Payment(bedrag=Decimal("650.00"), valuta="EUR", tegenpartij_naam="Jan",
                    tegenpartij_iban=None, omschrijving="huur", datum=date(2026, 7, 5)),
        ]


class FakeBunqClientTeWeinig:
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        return [
            Payment(bedrag=Decimal("300.00"), valuta="EUR", tegenpartij_naam="Jan",
                    tegenpartij_iban=None, omschrijving="huur", datum=date(2026, 7, 5)),
        ]


@pytest.fixture
def verstuurde_mails(monkeypatch):
    verstuurd = []

    def _fake_verstuur_email(config, aan, onderwerp, tekst, bcc=None):
        verstuurd.append({"aan": aan, "onderwerp": onderwerp, "tekst": tekst})

    monkeypatch.setattr(runner, "verstuur_email", _fake_verstuur_email)
    return verstuurd


def test_stuurt_melding_als_alle_kamers_betaald(monkeypatch, tmp_path, verstuurde_mails):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    run_check(_config(tmp_path), _pand(), dry_run=False, vandaag=date(2026, 7, 20))

    assert len(verstuurde_mails) == 1
    assert verstuurde_mails[0]["aan"] == "eigenaar@example.com"
    assert "Mahoniestraat 15" in verstuurde_mails[0]["onderwerp"]
    assert "volledig ontvangen" in verstuurde_mails[0]["tekst"].lower()


def test_geen_melding_als_niet_alle_kamers_betaald(monkeypatch, tmp_path, verstuurde_mails):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientTeWeinig)

    run_check(_config(tmp_path), _pand(), dry_run=False)

    assert verstuurde_mails == []


def test_geen_melding_zonder_kamers(monkeypatch, tmp_path, verstuurde_mails):
    def _lege_sheet_factory(config, pand):
        return FakeSheetClient(config, pand, tenants=[])

    monkeypatch.setattr(runner, "SheetClient", _lege_sheet_factory)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    run_check(_config(tmp_path), _pand(), dry_run=False)

    assert verstuurde_mails == []


def test_geen_melding_zonder_bcc_adressen(monkeypatch, tmp_path, verstuurde_mails):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    run_check(_config(tmp_path, email_bcc=[]), _pand(extra_bcc=[]), dry_run=False)

    assert verstuurde_mails == []


def test_melding_wordt_maar_eenmaal_per_maand_verstuurd(monkeypatch, tmp_path, verstuurde_mails):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)
    config = _config(tmp_path)
    pand = _pand()

    run_check(config, pand, dry_run=False, vandaag=date(2026, 7, 20))
    run_check(config, pand, dry_run=False, vandaag=date(2026, 7, 20))  # bv. nogmaals op "Nu controleren" geklikt

    assert len(verstuurde_mails) == 1


def test_dry_run_stuurt_nooit_een_melding(monkeypatch, tmp_path, verstuurde_mails):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    run_check(_config(tmp_path), _pand(), dry_run=True)

    assert verstuurde_mails == []


def test_melding_gebruikt_ook_pand_specifieke_extra_bcc(monkeypatch, tmp_path, verstuurde_mails):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    run_check(_config(tmp_path), _pand(extra_bcc=["justin@example.com"]), dry_run=False, vandaag=date(2026, 7, 20))

    assert verstuurde_mails[0]["aan"] == "eigenaar@example.com, justin@example.com"


class FakeSheetClientHistorieFaalt(FakeSheetClient):
    """Simuleert een falende Historie-sheet-schrijfactie (bv. een tijdelijke
    Google Sheets-hapering), terwijl write_results wel gewoon lukt."""

    def upsert_history(self, results, maand):
        raise RuntimeError("Google Sheets tijdelijk niet bereikbaar")


def test_falende_historie_schrijfactie_stopt_de_rest_van_run_check_niet(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientHistorieFaalt)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    from kamerverhuur_scanner import state

    tenants, results, unmatched = run_check(_config(tmp_path), _pand(), dry_run=False)

    assert len(results) == 1
    cache = state.load("mahoniestraat", state_dir=str(tmp_path))
    assert cache is not None
    assert cache["resultaten"][0]["kamer"] == "1"
