"""Tests voor runner.backfill_geschiedenis: vult de Historie-tab in één keer
aan met zoveel mogelijk voorgaande maanden, op basis van de huidige
huurderslijst - en de maand-voor-maand verdeling op basis van de vaste
"effectieve maand"-regel (1e t/m 17e van de maand telt voor die maand, 18e
t/m einde van de maand voor de maand erna). Bewust GEEN cumulatieve/lopende-
balans-aanpak over de hele periode - dat zou een huurverhoging halverwege de
reeks alle latere maanden laten verschuiven."""
import dataclasses
from datetime import date
from decimal import Decimal

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Pand, Payment, Status, Tenant
from kamerverhuur_scanner.runner import _verdeel_over_maanden, _voorgaande_maanden, backfill_geschiedenis
import kamerverhuur_scanner.runner as runner

VERWACHT = Decimal("650.00")
TOLERANTIE = Decimal("0.01")
MAANDEN_3 = [(2026, 4), (2026, 5), (2026, 6)]


def _betaling(bedrag: str, datum: date) -> Payment:
    return Payment(bedrag=Decimal(bedrag), valuta="EUR", tegenpartij_naam="Jan", tegenpartij_iban=None,
                   omschrijving="huur", datum=datum)


def test_voorgaande_maanden_binnen_hetzelfde_jaar():
    assert _voorgaande_maanden(date(2026, 7, 8), 3) == [(2026, 4), (2026, 5), (2026, 6)]


def test_voorgaande_maanden_over_jaargrens_heen():
    assert _voorgaande_maanden(date(2026, 2, 1), 3) == [(2025, 11), (2025, 12), (2026, 1)]


def test_voorgaande_maanden_nul_geeft_lege_lijst():
    assert _voorgaande_maanden(date(2026, 7, 8), 0) == []


def test_verdeel_over_maanden_altijd_op_tijd():
    betalingen = [
        _betaling("650.00", date(2026, 4, 3)),
        _betaling("650.00", date(2026, 5, 2)),
        _betaling("650.00", date(2026, 6, 4)),
    ]
    resultaat = _verdeel_over_maanden(VERWACHT, betalingen, MAANDEN_3, TOLERANTIE)

    assert resultaat["2026-04"] == (VERWACHT, Status.BETAALD, date(2026, 4, 3), VERWACHT)
    assert resultaat["2026-05"] == (VERWACHT, Status.BETAALD, date(2026, 5, 2), VERWACHT)
    assert resultaat["2026-06"] == (VERWACHT, Status.BETAALD, date(2026, 6, 4), VERWACHT)


def test_verdeel_over_maanden_op_de_17e_telt_nog_voor_die_maand():
    betalingen = [_betaling("650.00", date(2026, 5, 17))]
    resultaat = _verdeel_over_maanden(VERWACHT, betalingen, MAANDEN_3, TOLERANTIE)

    assert resultaat["2026-05"] == (VERWACHT, Status.BETAALD, date(2026, 5, 17), VERWACHT)
    assert resultaat["2026-06"] == (Decimal("0"), Status.NIET_ONTVANGEN, None, VERWACHT)


def test_verdeel_over_maanden_vanaf_de_18e_telt_voor_volgende_maand():
    # een huurder die halverwege de maand al vooruitbetaalt voor de maand erna
    betalingen = [_betaling("650.00", date(2026, 5, 18))]
    resultaat = _verdeel_over_maanden(VERWACHT, betalingen, MAANDEN_3, TOLERANTIE)

    assert resultaat["2026-05"] == (Decimal("0"), Status.NIET_ONTVANGEN, None, VERWACHT)
    assert resultaat["2026-06"] == (VERWACHT, Status.BETAALD, date(2026, 5, 18), VERWACHT)


def test_verdeel_over_maanden_wisselend_vroeg_laat_betalen_geeft_geen_valse_meldingen():
    # Regressie voor een huurder die de ene maand vroeg (eind vorige maand) en
    # de andere maand laat (begin de maand zelf) betaalt - dat mag niet als
    # "niet ontvangen"/"te veel ontvangen" door elkaar heen verschijnen.
    betalingen = [
        _betaling("650.00", date(2026, 3, 20)),  # vroeg voor april
        _betaling("650.00", date(2026, 5, 10)),  # "laat" voor mei, maar nog binnen de 17e
    ]
    maanden = [(2026, 3), (2026, 4), (2026, 5)]
    resultaat = _verdeel_over_maanden(VERWACHT, betalingen, maanden, TOLERANTIE)

    assert resultaat["2026-03"] == (Decimal("0"), Status.NIET_ONTVANGEN, None, VERWACHT)
    assert resultaat["2026-04"] == (VERWACHT, Status.BETAALD, date(2026, 3, 20), VERWACHT)
    assert resultaat["2026-05"] == (VERWACHT, Status.BETAALD, date(2026, 5, 10), VERWACHT)


def test_verdeel_over_maanden_buiten_de_teruggezochte_periode_wordt_genegeerd():
    betalingen = [_betaling("650.00", date(2026, 7, 3))]  # niet in MAANDEN_3
    resultaat = _verdeel_over_maanden(VERWACHT, betalingen, MAANDEN_3, TOLERANTIE)

    for maand_key in ("2026-04", "2026-05", "2026-06"):
        assert resultaat[maand_key][1] == Status.NIET_ONTVANGEN


def test_verdeel_over_maanden_nooit_betaald():
    resultaat = _verdeel_over_maanden(VERWACHT, [], MAANDEN_3, TOLERANTIE)

    for maand_key in ("2026-04", "2026-05", "2026-06"):
        ontvangen, status, betaaldatum, verwacht_deze_maand = resultaat[maand_key]
        assert ontvangen == Decimal("0")
        assert status == Status.NIET_ONTVANGEN
        assert betaaldatum is None
        assert verwacht_deze_maand == VERWACHT


def test_verdeel_over_maanden_gedeeltelijke_betaling_blijft_open():
    betalingen = [_betaling("300.00", date(2026, 4, 5))]
    resultaat = _verdeel_over_maanden(VERWACHT, betalingen, MAANDEN_3, TOLERANTIE)

    ontvangen, status, betaaldatum, _verwacht_deze_maand = resultaat["2026-04"]
    assert status == Status.TE_WEINIG
    assert ontvangen == Decimal("300.00")
    # er is wel degelijk iets ontvangen die maand, dus de datum blijft zichtbaar
    assert betaaldatum == date(2026, 4, 5)


def test_verdeel_over_maanden_huurverhoging_beinvloedt_andere_maanden_niet():
    # Regressietest: bij een cumulatieve/lopende-balans-aanpak zou een
    # huurverhoging halverwege de reeks alle latere maanden laten verschuiven
    # (foutief "vol betaald tegen het nieuwe/hogere bedrag" of "te weinig"
    # tonen voor maanden die op het moment zelf gewoon correct betaald waren).
    # Elke maand moet onafhankelijk beoordeeld worden tegen wat er die maand
    # ECHT binnenkwam.
    maanden = [(2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5)]
    oude_huur = Decimal("600.00")
    nieuwe_huur = Decimal("650.00")  # huidig verwacht bedrag (na verhoging in maart)
    betalingen = [
        _betaling("600.00", date(2026, 1, 3)),
        _betaling("600.00", date(2026, 2, 3)),
        _betaling("600.00", date(2026, 3, 3)),  # nog tegen het oude bedrag betaald
        _betaling("650.00", date(2026, 4, 3)),  # vanaf hier de nieuwe huur
        _betaling("650.00", date(2026, 5, 3)),
    ]
    resultaat = _verdeel_over_maanden(nieuwe_huur, betalingen, maanden, TOLERANTIE)

    # de maanden vóór de verhoging tonen gewoon wat er toen echt binnenkwam
    # (600, minder dan het huidige verwachte bedrag) - geen kunstmatig
    # "volledig betaald tegen het nieuwe bedrag" of weggehaalde/verschoven
    # bedragen door latere maanden.
    for maand_key in ("2026-01", "2026-02", "2026-03"):
        ontvangen, status, _betaaldatum, _verwacht_deze_maand = resultaat[maand_key]
        assert ontvangen == oude_huur
        assert status == Status.TE_WEINIG

    # de maanden na de verhoging zijn gewoon "Betaald" en blijven dat ook -
    # geen achterstand die van de oudere maanden wordt "doorgeschoven".
    for maand_key in ("2026-04", "2026-05"):
        ontvangen, status, _betaaldatum, _verwacht_deze_maand = resultaat[maand_key]
        assert ontvangen == nieuwe_huur
        assert status == Status.BETAALD


def test_verdeel_over_maanden_inhaalbetaling_lost_gemiste_maand_af():
    # Henri mist april (niks ontvangen) en betaalt in mei in één keer 2x de
    # huur - dat mag niet als "te veel ontvangen" voor mei verschijnen, want
    # hij is daarmee gewoon weer helemaal bij.
    betalingen = [_betaling("1300.00", date(2026, 5, 5))]
    resultaat = _verdeel_over_maanden(VERWACHT, betalingen, MAANDEN_3, TOLERANTIE)

    assert resultaat["2026-04"] == (Decimal("0"), Status.NIET_ONTVANGEN, None, VERWACHT)
    ontvangen, status, betaaldatum, _verwacht = resultaat["2026-05"]
    assert status == Status.BETAALD
    assert ontvangen == Decimal("1300.00")  # het ontvangen bedrag zelf blijft zichtbaar zoals het echt binnenkwam
    assert betaaldatum == date(2026, 5, 5)
    assert resultaat["2026-06"] == (Decimal("0"), Status.NIET_ONTVANGEN, None, VERWACHT)


def test_verdeel_over_maanden_inhaalbetaling_met_extra_overschot_telt_als_te_veel():
    betalingen = [_betaling("1400.00", date(2026, 5, 5))]  # 650 tekort april aflossen + 100 te veel
    resultaat = _verdeel_over_maanden(VERWACHT, betalingen, MAANDEN_3, TOLERANTIE)

    assert resultaat["2026-04"][1] == Status.NIET_ONTVANGEN
    assert resultaat["2026-05"][1] == Status.TE_VEEL


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
        self.dedupliceer_aangeroepen = False

    def get_tenants(self):
        return [Tenant(row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"))]

    def upsert_history(self, results, maand):
        self.upsert_calls.append((maand, results))

    def dedupliceer_geschiedenis(self):
        self.dedupliceer_aangeroepen = True
        return 0


class FakeBunqClient:
    laatste_since = None

    def __init__(self, _config):
        pass

    def get_incoming_payments(self, pand, since):
        FakeBunqClient.laatste_since = since
        return [
            _betaling("650.00", date(2026, 4, 3)),   # op tijd voor april
            _betaling("650.00", date(2026, 5, 20)),  # vroeg voor juni (na de 17e van mei)
            # mei heeft dus geen eigen betaling - blijft "niet ontvangen"
            # betaling in de huidige maand (juli) hoort NIET meegenomen te worden door backfill
            _betaling("650.00", date(2026, 7, 3)),
        ]


def test_backfill_geschiedenis_slaat_huidige_maand_over(monkeypatch):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    aantal = backfill_geschiedenis(_config(), _pand(), aantal_maanden=3, vandaag=date(2026, 7, 8))

    assert aantal == 3
    # since moet vanaf de 18e van de maand vóór de vroegste teruggezochte
    # maand (april) beginnen, dus de 18e maart
    assert FakeBunqClient.laatste_since == date(2026, 3, 18)


def test_backfill_geschiedenis_ruimt_eerst_dubbele_regels_op(monkeypatch):
    sheet_instances = []

    def _sheet_factory(config, pand):
        instance = FakeSheetClient(config, pand)
        sheet_instances.append(instance)
        return instance

    monkeypatch.setattr(runner, "SheetClient", _sheet_factory)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    backfill_geschiedenis(_config(), _pand(), aantal_maanden=3, vandaag=date(2026, 7, 8))

    assert sheet_instances[0].dedupliceer_aangeroepen is True


def test_backfill_geschiedenis_gebruikt_effectieve_maand_per_betaling(monkeypatch):
    sheet_instances = []

    def _sheet_factory(config, pand):
        instance = FakeSheetClient(config, pand)
        sheet_instances.append(instance)
        return instance

    monkeypatch.setattr(runner, "SheetClient", _sheet_factory)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    backfill_geschiedenis(_config(), _pand(), aantal_maanden=3, vandaag=date(2026, 7, 8))

    sheet = sheet_instances[0]
    per_maand = dict(sheet.upsert_calls)
    assert list(per_maand.keys()) == ["2026-04", "2026-05", "2026-06"]

    april_resultaat = per_maand["2026-04"][0]
    assert april_resultaat.status == Status.BETAALD
    assert april_resultaat.gematchte_betalingen[0].datum == date(2026, 4, 3)

    mei_resultaat = per_maand["2026-05"][0]
    assert mei_resultaat.status == Status.NIET_ONTVANGEN
    assert mei_resultaat.ontvangen_bedrag == Decimal("0")

    # de betaling van 20 mei (na de 17e) telt voor juni, niet voor mei
    juni_resultaat = per_maand["2026-06"][0]
    assert juni_resultaat.status == Status.BETAALD
    assert juni_resultaat.gematchte_betalingen[0].datum == date(2026, 5, 20)


# --- bereken_winstoverzicht ---


class FakeBunqClientUitgaven:
    laatste_since = None

    def __init__(self, _config):
        pass

    def get_outgoing_payments(self, pand, since):
        FakeBunqClientUitgaven.laatste_since = since
        return [
            _uitgaande_betaling("100.00", date(2026, 5, 3)),
            _uitgaande_betaling("100.00", date(2026, 6, 3)),
            _uitgaande_betaling("250.00", date(2026, 7, 1), iban="NL00EENMALIG00000", naam="Bouwmarkt"),
        ]


def _uitgaande_betaling(bedrag, datum, iban="NL91ABNA0417164300", naam="Energieleverancier"):
    return Payment(bedrag=Decimal(bedrag), valuta="EUR", tegenpartij_naam=naam, tegenpartij_iban=iban,
                   omschrijving="Energie", datum=datum)


def test_bereken_winstoverzicht_herkent_terugkerende_lasten_en_negeert_eenmalige(monkeypatch):
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientUitgaven)

    overzicht = runner.bereken_winstoverzicht(_config(), _pand(), inkomsten=Decimal("1000.00"))

    assert [last.omschrijving for last in overzicht.lasten] == ["Energieleverancier"]
    assert overzicht.lasten[0].bedrag == Decimal("100.00")
    assert overzicht.belasting == Decimal("75.00")
    assert overzicht.onderhoud_reserve == Decimal("0")
    assert overzicht.winst == Decimal("1000.00") - Decimal("100.00") - Decimal("75.00")


def test_bereken_winstoverzicht_gebruikt_onderhoud_reserve_van_pand(monkeypatch):
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClientUitgaven)
    pand = dataclasses.replace(_pand(), onderhoud_reserve_per_maand=Decimal("60.00"))

    overzicht = runner.bereken_winstoverzicht(_config(), pand, inkomsten=Decimal("1000.00"))

    assert overzicht.onderhoud_reserve == Decimal("60.00")


# --- netto_huurinkomsten_deze_maand ---


def _instapper(kamer="1", startdatum="05-07-2026", borg="500.00"):
    return Tenant(
        row_index=2, naam="Jan", kamer=kamer, verwacht_bedrag=Decimal("650.00"),
        contract_startdatum=startdatum, borg_bedrag=Decimal(borg),
    )


def _cache_regel(kamer="1", ontvangen="1000.00"):
    return {"kamer": kamer, "naam": "Jan", "verwacht_bedrag": "650.00", "ontvangen_bedrag": ontvangen}


def test_netto_huurinkomsten_zonder_instapmaand_telt_volledig_mee():
    tenant = Tenant(row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"))
    totaal = runner.netto_huurinkomsten_deze_maand([tenant], [_cache_regel(ontvangen="650.00")], vandaag=date(2026, 7, 15))
    assert totaal == Decimal("650.00")


def test_netto_huurinkomsten_trekt_borg_af_in_de_instapmaand_zelf():
    tenant = _instapper(startdatum="05-07-2026", borg="500.00")
    # 1000 ontvangen (pro-rata huur + borg samen) - 500 borg = 500 netto
    totaal = runner.netto_huurinkomsten_deze_maand([tenant], [_cache_regel(ontvangen="1000.00")], vandaag=date(2026, 7, 15))
    assert totaal == Decimal("500.00")


def test_netto_huurinkomsten_trekt_borg_af_bij_vooruitbetaling_maand_ervoor():
    # startdatum is augustus, maar het instapbedrag (incl. borg) is al in
    # juli vooruitbetaald - juli's cache moet de borg dan ook afgetrokken zien.
    tenant = _instapper(startdatum="03-08-2026", borg="500.00")
    totaal = runner.netto_huurinkomsten_deze_maand([tenant], [_cache_regel(ontvangen="1150.00")], vandaag=date(2026, 7, 20))
    assert totaal == Decimal("650.00")


def test_netto_huurinkomsten_gaat_niet_onder_nul():
    tenant = _instapper(startdatum="28-07-2026", borg="500.00")
    totaal = runner.netto_huurinkomsten_deze_maand([tenant], [_cache_regel(ontvangen="100.00")], vandaag=date(2026, 7, 30))
    assert totaal == Decimal("0")


def test_netto_huurinkomsten_kamer_niet_meer_in_tenants_telt_gewoon_mee():
    totaal = runner.netto_huurinkomsten_deze_maand([], [_cache_regel(kamer="3", ontvangen="650.00")], vandaag=date(2026, 7, 15))
    assert totaal == Decimal("650.00")


def test_netto_huurinkomsten_meerdere_kamers_alleen_instapper_wordt_gecorrigeerd():
    instapper = _instapper(kamer="1", startdatum="05-07-2026", borg="500.00")
    zittende_huurder = Tenant(row_index=3, naam="Piet", kamer="2", verwacht_bedrag=Decimal("700.00"),
                               contract_startdatum="01-01-2025", borg_bedrag=Decimal("500.00"))
    totaal = runner.netto_huurinkomsten_deze_maand(
        [instapper, zittende_huurder],
        [_cache_regel(kamer="1", ontvangen="1000.00"), _cache_regel(kamer="2", ontvangen="700.00")],
        vandaag=date(2026, 7, 15),
    )
    assert totaal == Decimal("500.00") + Decimal("700.00")
