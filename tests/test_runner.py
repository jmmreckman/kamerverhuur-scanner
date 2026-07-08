"""Tests voor runner.backfill_geschiedenis: vult de Historie-tab in één keer
aan met zoveel mogelijk voorgaande maanden, op basis van de huidige
huurderslijst."""
from datetime import date
from decimal import Decimal

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Pand, Payment, Tenant
from kamerverhuur_scanner.runner import _voorgaande_maanden, backfill_geschiedenis
import kamerverhuur_scanner.runner as runner


def test_voorgaande_maanden_binnen_hetzelfde_jaar():
    assert _voorgaande_maanden(date(2026, 7, 8), 3) == [(2026, 4), (2026, 5), (2026, 6)]


def test_voorgaande_maanden_over_jaargrens_heen():
    assert _voorgaande_maanden(date(2026, 2, 1), 3) == [(2025, 11), (2025, 12), (2026, 1)]


def test_voorgaande_maanden_nul_geeft_lege_lijst():
    assert _voorgaande_maanden(date(2026, 7, 8), 0) == []


def _pand() -> Pand:
    return Pand(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="x",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        google_drive_folder_id=None, bunq_rekening_iban="NL91ABNA0417164300",
    )


def _config() -> Config:
    return Config(
        google_service_account_file="fake.json", properties_file="properties.json",
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file="users.json", flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14,
    )


class FakeSheetClient:
    def __init__(self, _config, _pand):
        self.upsert_calls = []

    def get_tenants(self):
        return [Tenant(row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"))]

    def upsert_history(self, results, maand):
        self.upsert_calls.append((maand, results))


class FakeBunqClient:
    laatste_since = None

    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        FakeBunqClient.laatste_since = since
        return [
            Payment(bedrag=Decimal("650.00"), valuta="EUR", tegenpartij_naam="Jan",
                    tegenpartij_iban=None, omschrijving="huur mei", datum=date(2026, 5, 15)),
            Payment(bedrag=Decimal("650.00"), valuta="EUR", tegenpartij_naam="Jan",
                    tegenpartij_iban=None, omschrijving="huur juni", datum=date(2026, 6, 20)),
            # betaling in de huidige maand (juli) hoort NIET meegenomen te worden door backfill
            Payment(bedrag=Decimal("650.00"), valuta="EUR", tegenpartij_naam="Jan",
                    tegenpartij_iban=None, omschrijving="huur juli", datum=date(2026, 7, 3)),
        ]


def test_backfill_geschiedenis_slaat_huidige_maand_over(monkeypatch):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    aantal = backfill_geschiedenis(_config(), _pand(), aantal_maanden=3, vandaag=date(2026, 7, 8))

    assert aantal == 3
    # since moet op de vroegste maand (april) beginnen
    assert FakeBunqClient.laatste_since == date(2026, 4, 1)


def test_backfill_geschiedenis_matcht_per_maand_correct(monkeypatch):
    sheet_instances = []

    def _sheet_factory(config, pand):
        instance = FakeSheetClient(config, pand)
        sheet_instances.append(instance)
        return instance

    monkeypatch.setattr(runner, "SheetClient", _sheet_factory)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    backfill_geschiedenis(_config(), _pand(), aantal_maanden=3, vandaag=date(2026, 7, 8))

    sheet = sheet_instances[0]
    maanden = [maand for maand, _resultaten in sheet.upsert_calls]
    assert maanden == ["2026-04", "2026-05", "2026-06"]

    mei_resultaten = dict(sheet.upsert_calls)["2026-05"]
    assert mei_resultaten[0].ontvangen_bedrag == Decimal("650.00")

    april_resultaten = dict(sheet.upsert_calls)["2026-04"]
    assert april_resultaten[0].ontvangen_bedrag == Decimal("0")  # geen betaling die maand
