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
from kamerverhuur_scanner.models import HistorieRegel
from kamerverhuur_scanner.runner import (
    _instapbetaling_al_ontvangen,
    _parse_datum_dmy,
    _pro_rata_huur,
    _verwacht_bedrag_voor_maand,
    backfill_geschiedenis,
    run_check,
)
import kamerverhuur_scanner.runner as runner


@pytest.mark.parametrize("tekst", [
    "01-07-2026", "1-7-2026", "01/07/2026", "01.07.2026", "2026-07-01",
    "2026-07-01 00:00:00", "1 juli 2026", "01 Juli 2026", "  1 juli 2026  ",
])
def test_parse_datum_dmy_herkent_diverse_formaten(tekst):
    assert _parse_datum_dmy(tekst) == date(2026, 7, 1)


@pytest.mark.parametrize("tekst", ["", "onzin", "32-13-2026", "7 augustuss 2026"])
def test_parse_datum_dmy_geeft_none_bij_onherkenbare_tekst(tekst):
    assert _parse_datum_dmy(tekst) is None


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


def test_verwacht_bedrag_voor_maand_vlak_voor_instapmaand_is_ook_pro_rata_plus_borg():
    # het betaalverzoek wordt al bij het tekenen verstuurd, vaak (ruim) vóór
    # de daadwerkelijke ingangsdatum - de maand ervoor moet dus hetzelfde
    # instapbedrag verwachten, niet de volle "oude" maandhuur van de kamer.
    tenant = _tenant(contract_startdatum="01-08-2026", borg_bedrag=Decimal("1000.00"))
    assert _verwacht_bedrag_voor_maand(tenant, (2026, 7)) == Decimal("1600.00")


def test_verwacht_bedrag_voor_maand_instapmaand_zelf_verwacht_niets_extra_als_al_ontvangen():
    tenant = _tenant(contract_startdatum="01-08-2026", borg_bedrag=Decimal("1000.00"))
    assert _verwacht_bedrag_voor_maand(
        tenant, (2026, 8), instapbetaling_al_ontvangen=True
    ) == Decimal("0")


def test_verwacht_bedrag_voor_maand_instapmaand_verwacht_gewoon_instapbedrag_als_nog_niet_ontvangen():
    tenant = _tenant(contract_startdatum="01-08-2026", borg_bedrag=Decimal("1000.00"))
    assert _verwacht_bedrag_voor_maand(
        tenant, (2026, 8), instapbetaling_al_ontvangen=False
    ) == Decimal("1600.00")


def test_verwacht_bedrag_voor_maand_twee_maanden_voor_instap_blijft_normale_huur():
    tenant = _tenant(contract_startdatum="01-08-2026", borg_bedrag=Decimal("1000.00"))
    assert _verwacht_bedrag_voor_maand(tenant, (2026, 6)) == Decimal("600.00")


# --- _instapbetaling_al_ontvangen ---


def test_instapbetaling_al_ontvangen_vindt_eerdere_volledige_maand():
    geschiedenis = [
        HistorieRegel(
            maand="2026-07", kamer="1", huurder="Henri", verwacht_bedrag=Decimal("1600.00"),
            ontvangen_bedrag=Decimal("1600.00"), status=Status.TE_VEEL,
        ),
    ]
    assert _instapbetaling_al_ontvangen(geschiedenis, "2026-08", Decimal("1600.00"), Decimal("0.01")) is True


def test_instapbetaling_al_ontvangen_negeert_maanden_erna():
    geschiedenis = [
        HistorieRegel(
            maand="2026-09", kamer="1", huurder="Henri", verwacht_bedrag=Decimal("600.00"),
            ontvangen_bedrag=Decimal("1600.00"), status=Status.TE_VEEL,
        ),
    ]
    assert _instapbetaling_al_ontvangen(geschiedenis, "2026-08", Decimal("1600.00"), Decimal("0.01")) is False


def test_instapbetaling_al_ontvangen_false_zonder_geschiedenis():
    assert _instapbetaling_al_ontvangen([], "2026-08", Decimal("1600.00"), Decimal("0.01")) is False


# --- run_check(): instapmaand-aanpassing tijdens de actuele controle ---


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
    )
    basis.update(overrides)
    return Config(**basis)


class FakeSheetClientInstapper:
    def __init__(self, _config, _pand):
        self.write_results_calls = []
        self.upsert_calls = []

    def get_tenants(self):
        return [_tenant(contract_startdatum="03-07-2026", borg_bedrag=Decimal("1000.00"))]

    def get_geschiedenis(self, kamer):
        return []

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


class FakeSheetClientInstapperAfronding(FakeSheetClientInstapper):
    def get_tenants(self):
        return [_tenant(verwacht_bedrag=Decimal("745.00"), contract_startdatum="13-07-2026", borg_bedrag=Decimal("1000.00"))]


class FakeBunqClientInstapperTweeBetalingen:
    """Huurder betaalt de borg en de eerste huur los, in twee betalingen -
    samen net iets minder dan de exacte pro-rata + borg door een klein
    afrondingsverschil (bv. een dag anders gerekend bij de ingangsdatum)."""
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        return [
            Payment(bedrag=Decimal("1000.00"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="borg", datum=date(2026, 7, 13)),
            Payment(bedrag=Decimal("447.00"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="eerste huur", datum=date(2026, 7, 14)),
        ]


def test_run_check_instapmaand_twee_betalingen_binnen_10_procent_is_betaald(monkeypatch, tmp_path):
    # Regressietest voor een echt gemelde situatie: borg + eerste huur in 2
    # losse overschrijvingen van dezelfde huurder, samen €1.447,00 tegen een
    # exact-berekende verwachting (pro-rata huur vanaf 13 juli + €1.000 borg)
    # van €1.456,61 - een verschil van maar €9,61 (0,7%), typisch het gevolg
    # van een dag verschil in de ingangsberekening. Dat moet dus gewoon
    # "Betaald" zijn, niet "Te weinig ontvangen".
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientInstapperAfronding)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientInstapperTweeBetalingen)

    _tenants, results, _unmatched = run_check(_config(tmp_path), _pand(), dry_run=True)

    assert results[0].ontvangen_bedrag == Decimal("1447.00")
    assert results[0].status == Status.BETAALD


class FakeSheetClientVooruitbetaald(FakeSheetClientInstapperExact):
    def get_tenants(self):
        # tekent en betaalt nu (deze maand), maar het huurcontract gaat pas
        # de 1e van vólgende maand in - typisch: net getekend, borg + eerste
        # (volle) maand huur al in één keer overgemaakt.
        volgende_maand = date.today().month % 12 + 1
        jaar = date.today().year + (1 if date.today().month == 12 else 0)
        return [_tenant(
            verwacht_bedrag=Decimal("870.00"),
            contract_startdatum=f"01-{volgende_maand:02d}-{jaar}", borg_bedrag=Decimal("1000.00"),
        )]


class FakeBunqClientVooruitbetaald:
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        # dag 3 i.p.v. date.today(): moet altijd vóór de 17e-effectieve-maand-
        # grens vallen (zie runner._EFFECTIEVE_MAAND_GRENSDAG), anders telt de
        # betaling per ongeluk al mee voor de vólgende maand als de test
        # toevallig laat in de maand draait.
        return [
            Payment(bedrag=Decimal("1870.00"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="borg + eerste huur", datum=date.today().replace(day=3)),
        ]


def test_run_check_vooruitbetaling_maand_voor_instap_is_niet_te_veel(monkeypatch, tmp_path):
    # Regressietest voor een echt gemelde situatie: huurder tekent en betaalt
    # de borg + volle eerste maandhuur al in de maand vóór de daadwerkelijke
    # ingangsdatum. Zonder de "maand vóór de instapmaand telt ook al mee"-
    # aanpassing werd dit vergeleken met de gewone maandhuur en verscheen het
    # als "Te veel ontvangen", terwijl het gewoon de correcte vooruitbetaling is.
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientVooruitbetaald)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientVooruitbetaald)

    _tenants, results, _unmatched = run_check(_config(tmp_path), _pand(), dry_run=True)

    assert results[0].ontvangen_bedrag == Decimal("1870.00")
    assert results[0].status == Status.BETAALD


# --- run_check(): late instap (ná de 17e) mag niet tussen wal en schip vallen ---


class FakeSheetClientLateInstap(FakeSheetClientInstapper):
    def get_tenants(self):
        # Start op de 24e - ná de 17e-effectieve-maand-grens.
        return [_tenant(verwacht_bedrag=Decimal("650.00"), contract_startdatum="24-07-2026", borg_bedrag=Decimal("500.00"))]


class FakeBunqClientLateInstap:
    """De instapbetaling komt logischerwijs pas rond/na de late startdatum
    binnen - hier op de 27e, ruim ná de 17e-grens."""
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        return [
            Payment(bedrag=Decimal("667.74"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="borg + eerste huur", datum=date(2026, 7, 27)),
        ]


def test_run_check_late_instap_na_17e_telt_toch_voor_instapmaand(monkeypatch, tmp_path):
    # Regressietest voor een echt gemelde situatie: een huurder die pas ná de
    # 17e instrekt (hier de 24e) en de instapbetaling logischerwijs ook pas
    # rond die datum doet (hier de 27e). Zonder instap-bewuste uitzondering op
    # de 17e-grens (zie _effectieve_maand_voor_instap) verdween deze betaling
    # structureel uit beeld: te laat voor de instapmaand zelf, terwijl de
    # vólgende maand alweer de volle (niet-pro-rata) huur verwacht - geen van
    # beide maanden zou 'm ooit als "Betaald" herkennen.
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientLateInstap)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientLateInstap)

    _tenants, results, unmatched = run_check(
        _config(tmp_path), _pand(), dry_run=True, vandaag=date(2026, 7, 27),
    )

    assert unmatched == []
    assert len(results) == 1
    assert results[0].ontvangen_bedrag == Decimal("667.74")
    assert results[0].status == Status.BETAALD


class FakeSheetClientVroegeInstapTrageBetaling(FakeSheetClientInstapper):
    def get_tenants(self):
        # Start op de 5e - vóór de 17e-grens - maar de betaling zelf komt
        # pas veel later in de maand binnen (bv. een trage internationale
        # overschrijving).
        return [_tenant(verwacht_bedrag=Decimal("650.00"), contract_startdatum="05-07-2026", borg_bedrag=Decimal("500.00"))]


class FakeBunqClientVroegeInstapTrageBetaling:
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        return [
            Payment(bedrag=Decimal("1066.13"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="borg + eerste huur", datum=date(2026, 7, 27)),
        ]


def test_run_check_vroege_instap_met_trage_betaling_na_17e_telt_ook(monkeypatch, tmp_path):
    # De 17e-grens is niet alleen relevant als de startdatum zelf laat in de
    # maand valt: ook een huurder die al vroeg (voor de 17e) instapt, maar
    # wiens instapbetaling om wat voor reden dan ook pas later die maand
    # binnenkomt (hier: internationale overschrijving), mag niet buiten de
    # boot vallen - een betaling binnen iemands eigen instapmaand is per
    # definitie nooit een vooruitbetaling voor de maand erna.
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientVroegeInstapTrageBetaling)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientVroegeInstapTrageBetaling)

    _tenants, results, unmatched = run_check(
        _config(tmp_path), _pand(), dry_run=True, vandaag=date(2026, 7, 27),
    )

    assert unmatched == []
    assert results[0].ontvangen_bedrag == Decimal("1066.13")
    assert results[0].status == Status.BETAALD


class FakeSheetClientLateVooruitbetalingVoorInstap(FakeSheetClientInstapper):
    def get_tenants(self):
        # Trekt pas 1 augustus in, maar het betaalverzoek is al bij het
        # tekenen verstuurd - de betaling zelf komt pas laat in juli binnen
        # (na de 17e-grens).
        return [_tenant(verwacht_bedrag=Decimal("650.00"), contract_startdatum="01-08-2026", borg_bedrag=Decimal("500.00"))]


class FakeBunqClientLateVooruitbetalingVoorInstap:
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        return [
            Payment(bedrag=Decimal("1150.00"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="borg + eerste huur", datum=date(2026, 7, 27)),
        ]


def test_run_check_late_vooruitbetaling_in_maand_voor_instap_telt_voor_die_maand(monkeypatch, tmp_path):
    # Regressietest voor een echt gemelde situatie: een huurder trekt pas de
    # 1e van vólgende maand in, maar het betaalverzoek (borg + volle eerste
    # maandhuur) is al bij het tekenen verstuurd en komt pas ná de 17e-grens
    # in de maand ervóór binnen. _verwacht_bedrag_voor_maand() verwacht dat
    # bedrag onvoorwaardelijk al in die maand ervóór - zonder de bijpassende
    # uitzondering in _effectieve_maand_voor_instap() schoof de gewone
    # 17e-regel zo'n late betaling per ongeluk door naar de instapmaand zelf,
    # waar niets meer op hem paste (want in de instapmaand zelf werd dan
    # gewoon weer het volledige instapbedrag verwacht, ongeacht dat het al
    # eerder betaald was) - de betaling verscheen dan structureel als
    # "niet-gekoppeld" en de kamer bleef "Nog niet ontvangen" tonen.
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientLateVooruitbetalingVoorInstap)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientLateVooruitbetalingVoorInstap)

    _tenants, results, unmatched = run_check(
        _config(tmp_path), _pand(), dry_run=True, vandaag=date(2026, 7, 27),
    )

    assert unmatched == []
    assert results[0].ontvangen_bedrag == Decimal("1150.00")
    assert results[0].status == Status.BETAALD


class FakeSheetClientGevestigdeHuurderOudeInstapmaand(FakeSheetClientInstapper):
    def get_tenants(self):
        # Al lang gevestigde huurder - "Contract startdatum" staat nog op de
        # historische instapmaand (juni), maar dat is allang afgehandeld.
        return [_tenant(naam="Stefania", verwacht_bedrag=Decimal("745.00"), contract_startdatum="01-06-2026")]

    def get_geschiedenis(self, kamer):
        # Juni (haar instapmaand) is al lang geleden volledig ontvangen.
        return [
            HistorieRegel(
                maand="2026-06", kamer="1", huurder="Stefania", verwacht_bedrag=Decimal("745.00"),
                ontvangen_bedrag=Decimal("745.00"), status=Status.BETAALD,
            ),
        ]


class FakeBunqClientGevestigdeHuurderOudeInstapmaand:
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        # Gewone (iets vroege) huur voor juli, betaald op 30 juni - dus ná de
        # 17e-grens in juni, en toevallig in dezelfde kalendermaand als haar
        # (allang afgehandelde) instapdatum.
        return [
            Payment(bedrag=Decimal("745.00"), valuta="EUR", tegenpartij_naam="Stefania", tegenpartij_iban=None,
                    omschrijving="Rent July Stefania", datum=date(2026, 6, 30)),
        ]


def test_run_check_gevestigde_huurder_met_oude_instapmaand_verliest_betaling_niet(monkeypatch, tmp_path):
    # Regressietest voor een echt gemelde situatie: een allang gevestigde
    # huurder wiens 'Contract startdatum' nog altijd de historische
    # instapmaand vermeldt (logisch, die verandert nooit) betaalt heel
    # normaal een beetje vroeg (30 juni, voor de 17e-grens al ná de vorige
    # maand) voor juli. Zonder de "instapbedrag al eerder ontvangen"-grens in
    # _hoort_bij_deze_maand() werd die betaling, puur omdat juni toevallig
    # ook haar instapmaand was, alsnog aan die allang afgehandelde
    # instapmaand vastgeplakt in plaats van aan juli - de betaling verdween
    # dan spoorloos: niet toegekend aan juli, maar ook niet zichtbaar bij
    # "niet-gekoppeld" (want voor juni's controle wordt niet meer gekeken).
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientGevestigdeHuurderOudeInstapmaand)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientGevestigdeHuurderOudeInstapmaand)

    _tenants, results, unmatched = run_check(
        _config(tmp_path), _pand(), dry_run=True, vandaag=date(2026, 7, 27),
    )

    assert unmatched == []
    assert results[0].ontvangen_bedrag == Decimal("745.00")
    assert results[0].status == Status.BETAALD


def test_run_check_late_instap_betaling_kan_bij_controle_zonder_tussenstap_ook_in_volgende_maand_meetellen(monkeypatch, tmp_path):
    # Bewust geaccepteerde afweging (zie het commentaar bij
    # _hoort_bij_deze_maand() in runner.py): de instap-uitzondering geldt
    # alleen zolang de gecontroleerde maand ook echt de instapmaand (of de
    # maand ervóór) is - dat voorkomt dat een allang gevestigde huurder een
    # heel gewone latere betaling permanent aan zijn/haar allang afgehandelde
    # instapmaand vastgeplakt krijgt (spoorloos verdwijnen). Keerzijde: als
    # augustus wordt gecontroleerd zónder dat juli ooit is gecontroleerd
    # (dus zonder dat de instapbetaling al ergens is vastgelegd), telt deze
    # late instapbetaling ook gewoon weer mee voor augustus, volgens de
    # normale 17e-regel - zichtbaar als "Te veel ontvangen" i.p.v. onzichtbaar
    # verloren te gaan. In de praktijk (elk uur een controle) is juli dan al
    # lang correct verwerkt vóórdat augustus ooit wordt gecontroleerd.
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientLateInstap)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientLateInstap)

    _tenants, results, unmatched = run_check(
        _config(tmp_path), _pand(), dry_run=True, vandaag=date(2026, 8, 1),
    )

    assert results[0].ontvangen_bedrag == Decimal("667.74")
    assert results[0].status == Status.TE_VEEL
    assert unmatched == []


class FakeSheetClientLateInstapPlusAndereHuurder(FakeSheetClientInstapper):
    def get_tenants(self):
        return [
            _tenant(
                kamer="1", naam="Henri", verwacht_bedrag=Decimal("650.00"),
                contract_startdatum="24-07-2026", borg_bedrag=Decimal("500.00"),
            ),
            # bestaande huurder, geen (late) instap deze maand - betaalt op de
            # 20e gewoon vooruit voor augustus, zoals gebruikelijk.
            _tenant(kamer="2", naam="Luisa", verwacht_bedrag=Decimal("650.00"), contract_startdatum=None),
        ]


class FakeBunqClientLateInstapPlusAndereHuurder:
    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        return [
            Payment(bedrag=Decimal("667.74"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="borg + eerste huur", datum=date(2026, 7, 27)),
            # Luisa's reguliere vooruitbetaling voor augustus - moet gewoon
            # voor augustus blijven tellen, ook al valt-ie in dezelfde
            # kalendermaand als Henri's late instap.
            Payment(bedrag=Decimal("650.00"), valuta="EUR", tegenpartij_naam="Luisa", tegenpartij_iban=None,
                    omschrijving="huur augustus", datum=date(2026, 7, 20)),
        ]


def test_run_check_late_instap_raakt_vooruitbetaling_andere_huurder_niet(monkeypatch, tmp_path):
    # De instap-uitzondering geldt per (huurder, betaling)-paar, niet globaal
    # voor de hele kalendermaand - Luisa's eigen, normale vooruitbetaling voor
    # augustus mag niet per ongeluk als "juli" meetellen alleen omdat Henri
    # toevallig deze maand laat instapt.
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClientLateInstapPlusAndereHuurder)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientLateInstapPlusAndereHuurder)

    _tenants, results_juli, _unmatched = run_check(
        _config(tmp_path), _pand(), dry_run=True, vandaag=date(2026, 7, 27),
    )
    luisa_juli = next(r for r in results_juli if r.tenant.kamer == "2")
    assert luisa_juli.status == Status.NIET_ONTVANGEN

    _tenants, results_augustus, _unmatched = run_check(
        _config(tmp_path), _pand(), dry_run=True, vandaag=date(2026, 8, 1),
    )
    luisa_augustus = next(r for r in results_augustus if r.tenant.kamer == "2")
    assert luisa_augustus.status == Status.BETAALD
    assert luisa_augustus.ontvangen_bedrag == Decimal("650.00")


# --- backfill_geschiedenis(): per-kamer terugzoeken vanaf de startdatum ---


class FakeSheetClientBackfill:
    def __init__(self, _config, _pand):
        self.upsert_calls = []
        self.dedupliceer_aangeroepen = False
        self.opgeschoond_voor = []

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

    def verwijder_geschiedenis_voor_instapdatum(self, kamer, huurder, oudste_geldige_maand):
        self.opgeschoond_voor.append((kamer, huurder, oudste_geldige_maand))
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
    # alleen voor Henri (bekende startdatum) worden oude, te-ver-terugreikende
    # historieregels opgeschoond - Luisa heeft geen bekende startdatum, dus
    # geen enkele maand is "te vroeg" om op te schonen.
    assert sheet.opgeschoond_voor == [("1", "Henri", "2026-05")]


class FakeBunqClientBackfillAfronding(FakeBunqClientBackfill):
    def get_incoming_payments(self, pand, since):
        return [
            # mei (instapmaand van Henri): €14,52 minder dan de exacte
            # pro-rata (384,52) - binnen de 10%-marge voor de instapmaand.
            Payment(bedrag=Decimal("370.00"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="huur", datum=date(2026, 5, 16)),
            # juni (gewone maand): zelfde afwijking van €14,52, maar dat is
            # hier GEEN instapmaand meer, dus moet gewoon "Te weinig" blijven.
            Payment(bedrag=Decimal("730.48"), valuta="EUR", tegenpartij_naam="Henri", tegenpartij_iban=None,
                    omschrijving="huur", datum=date(2026, 6, 2)),
            Payment(bedrag=Decimal("650.00"), valuta="EUR", tegenpartij_naam="Luisa", tegenpartij_iban=None,
                    omschrijving="huur", datum=date(2026, 1, 3)),
        ]


def test_backfill_geschiedenis_instapmaand_binnen_10_procent_is_betaald(monkeypatch):
    sheet_instances = []

    def _sheet_factory(config, pand):
        instance = FakeSheetClientBackfill(config, pand)
        sheet_instances.append(instance)
        return instance

    monkeypatch.setattr(runner, "SheetClient", _sheet_factory)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientBackfillAfronding)

    config = Config(
        google_service_account_file="fake.json", properties_file="properties.json",
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file="users.json", flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, state_dir=".",
    )
    backfill_geschiedenis(config, _pand(), aantal_maanden=12, vandaag=date(2026, 7, 8))

    per_maand = dict(sheet_instances[0].upsert_calls)
    mei_resultaat = next(r for r in per_maand["2026-05"] if r.tenant.kamer == "1")
    assert mei_resultaat.status == Status.BETAALD  # instapmaand: binnen 10%-marge

    juni_resultaat = next(r for r in per_maand["2026-06"] if r.tenant.kamer == "1")
    assert juni_resultaat.status == Status.TE_WEINIG  # gewone maand: geen ruimere marge


class FakeSheetClientBackfillIso(FakeSheetClientBackfill):
    def get_tenants(self):
        # Google Sheets slaat een datumcel soms op als ISO-formaat
        # (jjjj-mm-dd) i.p.v. platte tekst dd-mm-jjjj - moet ook werken.
        return [_tenant(kamer="1", naam="Henri", contract_startdatum="2026-05-16", verwacht_bedrag=Decimal("745.00"))]


def test_backfill_geschiedenis_herkent_iso_datumformaat(monkeypatch):
    sheet_instances = []

    def _sheet_factory(config, pand):
        instance = FakeSheetClientBackfillIso(config, pand)
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
    henri_maanden = {maand for maand, resultaten in per_maand.items() if any(r.tenant.kamer == "1" for r in resultaten)}
    # net als bij het dd-mm-jjjj-formaat: alleen mei en juni, niet de
    # standaard 12 maanden terug.
    assert henri_maanden == {"2026-05", "2026-06"}
