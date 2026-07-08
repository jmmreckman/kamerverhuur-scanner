"""Tests voor runner.backfill_geschiedenis: vult de Historie-tab in één keer
aan met zoveel mogelijk voorgaande maanden, op basis van de huidige
huurderslijst - en de maand-voor-maand verdeling (met één gerichte
uitzondering voor een inhaalbetaling na een gemiste maand) die voorkomt dat
zo'n inhaalbetaling de ene maand als 'Te veel' en de andere als 'Nog niet
ontvangen' laat zien terwijl de huurder gewoon laat was. Bewust GEEN
cumulatieve/lopende-balans-aanpak over de hele periode - dat zou een
huurverhoging halverwege de reeks alle latere maanden laten verschuiven."""
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

    assert resultaat["2026-04"] == (VERWACHT, Status.BETAALD, date(2026, 4, 3))
    assert resultaat["2026-05"] == (VERWACHT, Status.BETAALD, date(2026, 5, 2))
    assert resultaat["2026-06"] == (VERWACHT, Status.BETAALD, date(2026, 6, 4))


def test_verdeel_over_maanden_inhaalbetaling_schuift_terug_ipv_te_veel():
    # april op tijd, mei gemist, juni een dubbele betaling (inhalen van mei + juni ineens)
    betalingen = [
        _betaling("650.00", date(2026, 4, 3)),
        _betaling("1300.00", date(2026, 6, 10)),
    ]
    resultaat = _verdeel_over_maanden(VERWACHT, betalingen, MAANDEN_3, TOLERANTIE)

    assert resultaat["2026-04"] == (VERWACHT, Status.BETAALD, date(2026, 4, 3))
    # mei is met terugwerkende kracht 'Betaald' (laat) op de datum van de inhaalbetaling
    assert resultaat["2026-05"] == (VERWACHT, Status.BETAALD, date(2026, 6, 10))
    # juni is dus gewoon 'Betaald', NIET 'Te veel ontvangen'
    assert resultaat["2026-06"] == (VERWACHT, Status.BETAALD, date(2026, 6, 10))


def test_verdeel_over_maanden_nooit_betaald():
    resultaat = _verdeel_over_maanden(VERWACHT, [], MAANDEN_3, TOLERANTIE)

    for maand_key in ("2026-04", "2026-05", "2026-06"):
        ontvangen, status, betaaldatum = resultaat[maand_key]
        assert ontvangen == Decimal("0")
        assert status == Status.NIET_ONTVANGEN
        assert betaaldatum is None


def test_verdeel_over_maanden_gedeeltelijke_betaling_blijft_open():
    betalingen = [_betaling("300.00", date(2026, 4, 5))]
    resultaat = _verdeel_over_maanden(VERWACHT, betalingen, MAANDEN_3, TOLERANTIE)

    ontvangen, status, betaaldatum = resultaat["2026-04"]
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
        ontvangen, status, _betaaldatum = resultaat[maand_key]
        assert ontvangen == oude_huur
        assert status == Status.TE_WEINIG

    # de maanden na de verhoging zijn gewoon "Betaald" en blijven dat ook -
    # geen achterstand die van de oudere maanden wordt "doorgeschoven".
    for maand_key in ("2026-04", "2026-05"):
        ontvangen, status, _betaaldatum = resultaat[maand_key]
        assert ontvangen == nieuwe_huur
        assert status == Status.BETAALD


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
            _betaling("650.00", date(2026, 4, 3)),
            _betaling("1300.00", date(2026, 6, 10)),
            # betaling in de huidige maand (juli) hoort NIET meegenomen te worden door backfill
            _betaling("650.00", date(2026, 7, 3)),
        ]


def test_backfill_geschiedenis_slaat_huidige_maand_over(monkeypatch):
    monkeypatch.setattr(runner, "SheetClient", FakeSheetClient)
    monkeypatch.setattr(runner, "BunqClient", FakeBunqClient)

    aantal = backfill_geschiedenis(_config(), _pand(), aantal_maanden=3, vandaag=date(2026, 7, 8))

    assert aantal == 3
    # since moet op de vroegste maand (april) beginnen
    assert FakeBunqClient.laatste_since == date(2026, 4, 1)


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


def test_backfill_geschiedenis_verdeelt_inhaalbetaling_naar_vorige_maand(monkeypatch):
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

    for maand_key in per_maand:
        resultaat = per_maand[maand_key][0]
        assert resultaat.status == Status.BETAALD
        assert resultaat.ontvangen_bedrag == Decimal("650.00")

    # mei en juni zijn allebei via de inhaalbetaling van 10 juni afgehandeld
    assert per_maand["2026-05"][0].gematchte_betalingen[0].datum == date(2026, 6, 10)
    assert per_maand["2026-06"][0].gematchte_betalingen[0].datum == date(2026, 6, 10)
    assert per_maand["2026-04"][0].gematchte_betalingen[0].datum == date(2026, 4, 3)
