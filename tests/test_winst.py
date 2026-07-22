from datetime import date
from decimal import Decimal

from kamerverhuur_scanner.models import Payment
from kamerverhuur_scanner.winst import (
    BELASTING_PER_MAAND,
    Inkomst,
    bereken_winst,
    gecombineerde_winst_over_tijd,
    herken_terugkerende_lasten,
    verdeelde_winst,
)


def _inkomsten(bedrag: str) -> list[Inkomst]:
    return [Inkomst(kamer="1", naam="Jan", verwacht_bedrag=Decimal(bedrag))]


def _betaling(bedrag, datum, iban="NL91ABNA0417164300", naam="Energieleverancier", omschrijving="Energie"):
    return Payment(
        bedrag=Decimal(bedrag), valuta="EUR", tegenpartij_naam=naam, tegenpartij_iban=iban,
        omschrijving=omschrijving, datum=date.fromisoformat(datum),
    )


def test_herken_terugkerende_lasten_vindt_maandelijks_terugkerende_tegenpartij():
    betalingen = [
        _betaling("99.00", "2026-05-03"),
        _betaling("101.00", "2026-06-03"),
        _betaling("100.00", "2026-07-03"),
    ]
    lasten = herken_terugkerende_lasten(betalingen)
    assert len(lasten) == 1
    assert lasten[0].omschrijving == "Energieleverancier"
    assert lasten[0].bedrag == Decimal("100.00")
    assert lasten[0].sleutel == "nl91abna0417164300"


def test_herken_terugkerende_lasten_negeert_expliciet_genegeerde_tegenpartij():
    betalingen = [
        _betaling("500.00", "2026-04-01", iban="NL00JUR000000000", naam="Jur"),
        _betaling("500.00", "2026-05-01", iban="NL00JUR000000000", naam="Jur"),
        _betaling("500.00", "2026-06-01", iban="NL00JUR000000000", naam="Jur"),
    ]
    lasten = herken_terugkerende_lasten(betalingen, genegeerd={"nl00jur000000000"})
    assert lasten == []


def test_herken_terugkerende_lasten_negeert_eenmalige_uitgave():
    betalingen = [_betaling("250.00", "2026-07-10", iban="NL00EENMALIG000000", naam="Bouwmarkt")]
    assert herken_terugkerende_lasten(betalingen) == []


def test_herken_terugkerende_lasten_dubbele_betaling_in_dezelfde_maand_telt_niet_als_terugkerend():
    # twee keer dezelfde tegenpartij binnen 1 kalendermaand is geen bewijs
    # van een MAANDELIJKS terugkerende last (kan toeval zijn).
    betalingen = [
        _betaling("50.00", "2026-07-01", iban="NL00EENMAAND000000"),
        _betaling("50.00", "2026-07-15", iban="NL00EENMAAND000000"),
    ]
    assert herken_terugkerende_lasten(betalingen) == []


def test_herken_terugkerende_lasten_groepeert_op_naam_zonder_iban():
    betalingen = [
        _betaling("40.00", "2026-04-05", iban=None, naam="VvE Beheer"),
        _betaling("40.00", "2026-05-05", iban=None, naam="VvE Beheer"),
        _betaling("40.00", "2026-06-05", iban=None, naam="VvE Beheer"),
    ]
    lasten = herken_terugkerende_lasten(betalingen)
    assert len(lasten) == 1
    assert lasten[0].omschrijving == "VvE Beheer"


def test_herken_terugkerende_lasten_sorteert_van_hoog_naar_laag():
    betalingen = [
        _betaling("40.00", "2026-04-01", iban="NL00A", naam="Internet"),
        _betaling("40.00", "2026-05-01", iban="NL00A", naam="Internet"),
        _betaling("40.00", "2026-06-01", iban="NL00A", naam="Internet"),
        _betaling("1350.00", "2026-04-01", iban="NL00B", naam="Hypotheek"),
        _betaling("1350.00", "2026-05-01", iban="NL00B", naam="Hypotheek"),
        _betaling("1350.00", "2026-06-01", iban="NL00B", naam="Hypotheek"),
    ]
    lasten = herken_terugkerende_lasten(betalingen)
    assert [last.omschrijving for last in lasten] == ["Hypotheek", "Internet"]


def test_herken_terugkerende_lasten_negeert_wekelijkse_boodschappenbezorging():
    # Picnic/Flink e.d. komen vaak wekelijks (4-5x/maand) bij dezelfde
    # tegenpartij terug - dat MOET geen "vaste last" worden, ook al voldoet
    # het aan de 3-maanden-eis, want het is geen vast maandelijks bedrag.
    betalingen = [
        _betaling(bedrag, datum, iban="NL00PICNIC0000000", naam="Picnic")
        for maand in ("04", "05", "06")
        for bedrag, datum in [("35.00", f"2026-{maand}-03"), ("40.00", f"2026-{maand}-10"),
                               ("28.00", f"2026-{maand}-17"), ("33.00", f"2026-{maand}-24")]
    ]
    assert herken_terugkerende_lasten(betalingen) == []


def test_herken_terugkerende_lasten_precies_1x_per_maand_over_3_maanden_telt_wel():
    betalingen = [
        _betaling("49.99", "2026-04-15", iban="NL00KPN00000000000", naam="KPN"),
        _betaling("49.99", "2026-05-15", iban="NL00KPN00000000000", naam="KPN"),
        _betaling("49.99", "2026-06-15", iban="NL00KPN00000000000", naam="KPN"),
    ]
    lasten = herken_terugkerende_lasten(betalingen)
    assert len(lasten) == 1
    assert lasten[0].omschrijving == "KPN"


def test_bereken_winst_trekt_belasting_onderhoud_en_lasten_af():
    lasten = [herken_terugkerende_lasten([
        _betaling("100.00", "2026-04-01"), _betaling("100.00", "2026-05-01"), _betaling("100.00", "2026-06-01"),
    ])[0]]
    overzicht = bereken_winst(_inkomsten("3507.01"), lasten=lasten, onderhoud_reserve=Decimal("60.00"))
    assert overzicht.inkomsten == Decimal("3507.01")
    assert overzicht.belasting == BELASTING_PER_MAAND
    assert overzicht.totaal_lasten == Decimal("100.00") + BELASTING_PER_MAAND + Decimal("60.00")
    assert overzicht.winst == Decimal("3507.01") - overzicht.totaal_lasten


def test_bereken_winst_zonder_onderhoud_reserve_telt_als_nul():
    overzicht = bereken_winst(_inkomsten("1000.00"), lasten=[], onderhoud_reserve=None)
    assert overzicht.onderhoud_reserve == Decimal("0")
    assert overzicht.totaal_lasten == BELASTING_PER_MAAND


def test_winstoverzicht_inkomsten_is_som_van_specificatie():
    overzicht = bereken_winst(
        [Inkomst(kamer="1", naam="Jan", verwacht_bedrag=Decimal("650.00")),
         Inkomst(kamer="2", naam="Piet", verwacht_bedrag=Decimal("700.00"))],
        lasten=[], onderhoud_reserve=None,
    )
    assert overzicht.inkomsten == Decimal("1350.00")


def test_verdeelde_winst_bij_1_beheerder_blijft_gelijk():
    assert verdeelde_winst(Decimal("1000.00"), aantal_beheerders=1) == Decimal("1000.00")


def test_verdeelde_winst_bij_meerdere_beheerders_wordt_gelijk_verdeeld():
    assert verdeelde_winst(Decimal("1000.00"), aantal_beheerders=2) == Decimal("500.00")
    assert verdeelde_winst(Decimal("1000.00"), aantal_beheerders=3) == Decimal("333.33")


def test_gecombineerde_winst_over_tijd_telt_panden_op_per_datum():
    reeksen = {
        "mahoniestraat": [{"datum": "2026-07-01", "winst": "1000.00"}],
        "baumannlaan": [{"datum": "2026-07-01", "winst": "500.00"}],
    }
    resultaat = gecombineerde_winst_over_tijd(reeksen, {"mahoniestraat": 1, "baumannlaan": 1})
    assert resultaat == [{"datum": "2026-07-01", "winst": "1500.00"}]


def test_gecombineerde_winst_over_tijd_deelt_bij_meerdere_beheerders():
    reeksen = {"mahoniestraat": [{"datum": "2026-07-01", "winst": "1000.00"}]}
    resultaat = gecombineerde_winst_over_tijd(reeksen, {"mahoniestraat": 2})
    assert resultaat == [{"datum": "2026-07-01", "winst": "500.00"}]


def test_gecombineerde_winst_over_tijd_forward_fillt_ontbrekende_datums():
    # baumannlaan heeft alleen een punt op 1 juli, mahoniestraat ook op 8 juli
    # - op 8 juli moet baumannlaan's LAATST BEKENDE punt (1 juli) nog meetellen.
    reeksen = {
        "mahoniestraat": [{"datum": "2026-07-01", "winst": "1000.00"}, {"datum": "2026-07-08", "winst": "1100.00"}],
        "baumannlaan": [{"datum": "2026-07-01", "winst": "500.00"}],
    }
    resultaat = gecombineerde_winst_over_tijd(reeksen, {"mahoniestraat": 1, "baumannlaan": 1})
    assert resultaat == [
        {"datum": "2026-07-01", "winst": "1500.00"},
        {"datum": "2026-07-08", "winst": "1600.00"},
    ]


def test_gecombineerde_winst_over_tijd_pand_zonder_datapunten_telt_niet_mee():
    reeksen = {"mahoniestraat": [{"datum": "2026-07-01", "winst": "1000.00"}], "leegpand": []}
    resultaat = gecombineerde_winst_over_tijd(reeksen, {"mahoniestraat": 1, "leegpand": 1})
    assert resultaat == [{"datum": "2026-07-01", "winst": "1000.00"}]
