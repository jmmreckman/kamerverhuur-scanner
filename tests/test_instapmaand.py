"""Tests voor de instapmaand-logica: een nieuwe huurder betaalt vaak een
pro-rata deel van de eerste maand plus de waarborgsom in één keer - dat mag
niet als "te veel ontvangen" verschijnen. En: backfill_geschiedenis() zoekt
per kamer terug vanaf de bekende 'Contract startdatum' i.p.v. altijd de
standaard 12 maanden, zodat er geen "niet ontvangen"-maanden verschijnen van
vóórdat de huurder er woonde."""
from datetime import date
from decimal import Decimal

import pytest

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Pand, Payment, Status, Tenant
from kamerverhuur_scanner.runner import (
    _pro_rata_huur,
    _verwacht_bedrag_voor_maand,
    backfill_geschiedenis,
    run_check,
)
import kamerverhuur_scanner.runner as runner


def test_pro_rata_huur_bij_start_op_de_1e_is_volle_maandhuur():
    assert _pro_rata_huur(Decimal("600.00"), date(2026, 4, 1)) == Decimal("600.00")


def test_pro_rata_huur_bij_start_halverwege_de_maand():
    # april heeft 30 dagen, start op de 11e = nog 20 dagen te gaan
    assert _pro_rata_huur(Decimal("600.00"), date(2026, 4, 11)) == Decimal("400.00")


def _tenant(**overrides) -> Tenant:
    basis = dict(row_index=2, naam="Henri", kamer="1", verwacht_bedrag=Decimal("600.00"))
    basis.update(overrides)
    return Tenant(**basis)


def test_verwacht_bedrag_voor_maand_in_instapmaand_is_pro_rata_plus_borg():
    tenant = _tenant(contract_startdatum="11-04-2026", borg_bedrag=Decimal("1000.00"))
    assert _verwacht_bedrag_voor_maand(tenant, (2026, 4)) == Decimal("1400.00")


def test_verwacht_bedrag_voor_maand_buiten_instapmaand_blijft_normale_huur():
    tenant = _tenant(contract_startdatum="11-04-2026", borg_bedrag=Decimal("1000.00"))
    assert _verwacht_bedrag_voor_maand(tenant, (2026, 5)) == Decimal("600.00")


def test_verwacht_bedrag_voor_maand_zonder_startdatum_blijft_normale_huur():
    tenant = _tenant(contract_startdatum=None, borg_bedrag=Decimal("1000.00"))
    assert _verwacht_bedrag_voor_maand(tenant, (2026, 4)) == Decimal("600.00")


def test_verwacht_bedrag_voor_maand_zonder_borg_is_alleen_pro_rata():
    tenant = _tenant(contract_startdatum="11-04-2026", borg_bedrag=None)
    assert _verwacht_bedrag_voor_maand(tenant, (2026, 4)) == Decimal("400.00")


# --- run_check(): instapmaand-aanpassing tijdens de actuele controle ---


def _pand(**overrides) -> Pand:
    basis = dict(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="x",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        google_drive_folder_id=None, bunq_rekening_iban="NL91ABNA0417164300",
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
    )
    basis.update(overrides)
    return Config(**basis)


class FakeSheetClientInstapper:
    def __init__(self, _config, _pand):
        self.write_results_calls = []
        self.upsert_calls = []

    def get_tenants(self):
        return [_tenant(contract_startdatum="03-07-2026", borg_bedrag=Decimal("1000.00"))]

    def write_results(self, results):
        self.write_results_calls.append(results)

    def upsert_history(self, results, maand):
        self.upsert_calls.append((maand, results))


class FakeBunqClientInstapper:
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        # pro-rata huur (juli, start 3e) + borg in één betaling
        return [
            Payment(bedrag=Decimal("1560.00"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="huur + borg", datum=date(2026, 7, 3)),
        ]


def test_run_check_telt_pro_rata_plus_borg_niet_als_te_veel(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientInstapper)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientInstapper)

    _tenants, results, _unmatched = run_check(
        _config(tmp_path), _pand(), dry_run=True
    )

    assert len(results) == 1
    # juli heeft 31 dagen, start op de 3e = nog 29 dagen: 600 * 29/31 = 561,29
    # + 1000 borg = 1561,29 verwacht -> 1560 ontvangen valt (net) binnen "te weinig"
    # dus gebruiken we hier een exacte match om de kernclaim te toetsen: geen
    # "te veel ontvangen" meer voor een betaling die vroeger 2x de kale huur
    # zou hebben geleken.
    assert results[0].status != Status.TE_VEEL


class FakeSheetClientInstapperExact(FakeSheetClientInstapper):
    def get_tenants(self):
        # start op de 1e => pro-rata is exact de volle huur, geen afrondingsgedoe
        return [_tenant(verwacht_bedrag=Decimal("600.00"), contract_startdatum="01-07-2026", borg_bedrag=Decimal("1000.00"))]


class FakeBunqClientInstapperExact:
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        return [
            Payment(bedrag=Decimal("1600.00"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="huur + borg", datum=date(2026, 7, 3)),
        ]


def test_run_check_instapmaand_exacte_pro_rata_plus_borg_is_betaald(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientInstapperExact)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientInstapperExact)

    _tenants, results, _unmatched = run_check(_config(tmp_path), _pand(), dry_run=True)

    assert results[0].status == Status.BETAALD
    assert results[0].ontvangen_bedrag == Decimal("1600.00")


# --- backfill_geschiedenis(): per-kamer terugzoeken vanaf de startdatum ---


class FakeSheetClientBackfill:
    def __init__(self, _config, _pand):
        self.upsert_calls = []
        self.dedupliceer_aangeroepen = False

    def get_tenants(self):
        return [
            # 2 maanden geleden ingestapt (mei) - moet dus alleen mei/juni
            # krijgen, niet de standaard 12 maanden terug.
            _tenant(kamer="1", naam="Henri", contract_startdatum="16-05-2026", verwacht_bedrag=Decimal("745.00")),
            # geen bekende startdatum - valt terug op de standaard 12 maanden.
            _tenant(kamer="2", naam="Luisa", contract_startdatum=None, verwacht_bedrag=Decimal("650.00")),
        ]

    def upsert_history(self, results, maand):
        self.upsert_calls.append((maand, results))

    def dedupliceer_geschiedenis(self):
        self.dedupliceer_aangeroepen = True
        return 0


class FakeBunqClientBackfill:
    laatste_since = None

    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        FakeBunqClientBackfill.laatste_since = since
        return [
            # mei: pro-rata (16 dagen van 31) 745 * 16/31 = 384,52 + borg 0 = 384,52
            Payment(bedrag=Decimal("384.52"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="huur", datum=date(2026, 5, 16)),
            Payment(bedrag=Decimal("745.00"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="huur", datum=date(2026, 6, 2)),
            Payment(bedrag=Decimal("650.00"), valuta="EUR", tegenpartij_naam="Luisa", tegenpartij_iban=None,
                    omschrijving="huur", datum=date(2026, 1, 3)),
        ]


def test_backfill_geschiedenis_per_kamer_vanaf_startdatum(monkeypatch):
    sheet_instances = []

    def _sheet_factory(config, pand):
        instance = FakeSheetClientBackfill(config, pand)
        sheet_instances.append(instance)
        return instance

    monkeypatch.setattr(runner, "SheetClient", _sheet_factory)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientBackfill)

    config = Config(
        google_service_account_file="fake.json", properties_file="properties.json",
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file="users.json", flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, state_dir=".",
    )
    backfill_geschiedenis(config, _pand(), aantal_maanden=12, vandaag=date(2026, 7, 8))

    sheet = sheet_instances[0]
    per_maand = dict(sheet.upsert_calls)

    # Henri (kamer 1): alleen mei en juni geschreven, geen jaar-lang aan
    # "niet ontvangen"-regels van vóór zijn intrek.
    henri_maanden = {maand for maand, resultaten in per_maand.items() if any(r.tenant.kamer == "1" for r in resultaten)}
    assert henri_maanden == {"2026-05", "2026-06"}

    mei_resultaat = next(r for r in per_maand["2026-05"] if r.tenant.kamer == "1")
    assert mei_resultaat.status == Status.BETAALD
    assert mei_resultaat.tenant.verwacht_bedrag == Decimal("384.52")  # pro-rata, niet de volle 745

    juni_resultaat = next(r for r in per_maand["2026-06"] if r.tenant.kamer == "1")
    assert juni_resultaat.status == Status.BETAALD
    assert juni_resultaat.tenant.verwacht_bedrag == Decimal("745.00")  # gewone volle huur

    # Luisa (kamer 2, geen startdatum): valt terug op de standaard 12 maanden.
    luisa_maanden = {maand for maand, resultaten in per_maand.items() if any(r.tenant.kamer == "2" for r in resultaten)}
    assert len(luisa_maanden) == 12

    assert sheet.dedupliceer_aangeroepen is True
