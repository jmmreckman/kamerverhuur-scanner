"""Integratietest voor run_check(): een inhaalbetaling deze maand mag een
openstaand tekort uit de Historie van eerdere maand(en) eerst aflossen,
i.p.v. als 'te veel ontvangen' voor de huidige maand te tellen."""
from datetime import date
from decimal import Decimal

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import HistorieRegel, Pand, Payment, Status, Tenant
from kamerverhuur_scanner.runner import run_check
import kamerverhuur_scanner.runner as runner


def _pand() -> Pand:
    return Pand(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="x",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        bunq_rekening_iban="NL91ABNA0417164300",
    )


def _config(tmp_path) -> Config:
    return Config(
        google_service_account_file="fake.json", properties_file="properties.json",
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file="users.json", flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14,
        state_dir=str(tmp_path),
    )


class FakeSheetClientMetAchterstand:
    """Henri (kamer 1) miste vorige maand (745 verwacht, niks ontvangen) en
    betaalt deze maand in één keer 2x de huur."""

    def __init__(self, _config, _pand):
        self.upsert_calls = []

    def get_tenants(self):
        return [Tenant(row_index=2, naam="Henri", kamer="1", verwacht_bedrag=Decimal("745.00"))]

    def get_geschiedenis(self, kamer):
        return [
            HistorieRegel(
                maand="2026-06", kamer="1", huurder="Henri",
                verwacht_bedrag=Decimal("745.00"), ontvangen_bedrag=Decimal("0.00"),
                status=Status.NIET_ONTVANGEN,
            ),
        ]

    def write_results(self, results):
        self.write_results_calls = results

    def upsert_history(self, results, maand):
        self.upsert_calls.append((maand, results))


class FakeBunqClientInhaalbetaling:
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        return [
            Payment(bedrag=Decimal("1490.00"), valuta="EUR", tegenpartij_naam="Henri",
                    tegenpartij_iban=None, omschrijving="huur", datum=date.today().replace(day=5)),
        ]


def test_run_check_lost_openstaand_tekort_af_voor_te_veel_ontvangen(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientMetAchterstand)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientInhaalbetaling)

    _tenants, results, _unmatched = run_check(_config(tmp_path), _pand(), dry_run=True)

    assert len(results) == 1
    assert results[0].status == Status.BETAALD
