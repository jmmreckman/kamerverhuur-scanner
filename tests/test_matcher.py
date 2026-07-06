from datetime import date
from decimal import Decimal

from kamerverhuur_scanner.matcher import match_tenants_to_payments
from kamerverhuur_scanner.models import Payment, Status, Tenant

TOL = Decimal("0.01")


def _tenant(row=2, naam="Jan de Vries", kamer="1", bedrag="650.00", iban=None, zoekwoord=None):
    return Tenant(
        row_index=row,
        naam=naam,
        kamer=kamer,
        verwacht_bedrag=Decimal(bedrag),
        iban=iban,
        zoekwoord=zoekwoord,
    )


def _payment(bedrag="650.00", naam="J de Vries", iban=None, omschrijving="Huur juli"):
    return Payment(
        bedrag=Decimal(bedrag),
        valuta="EUR",
        tegenpartij_naam=naam,
        tegenpartij_iban=iban,
        omschrijving=omschrijving,
        datum=date(2026, 7, 3),
    )


def test_matcht_op_naam_en_bedrag_klopt():
    tenants = [_tenant()]
    payments = [_payment()]

    results, unmatched = match_tenants_to_payments(tenants, payments, TOL)

    assert unmatched == []
    assert results[0].status == Status.BETAALD
    assert results[0].ontvangen_bedrag == Decimal("650.00")


def test_niet_ontvangen_als_geen_betaling_matcht():
    tenants = [_tenant(naam="Piet Bakker")]
    payments = [_payment(naam="Iemand Anders", omschrijving="boodschappen")]

    results, unmatched = match_tenants_to_payments(tenants, payments, TOL)

    assert results[0].status == Status.NIET_ONTVANGEN
    assert results[0].ontvangen_bedrag == Decimal("0")
    assert len(unmatched) == 1


def test_te_weinig_ontvangen():
    tenants = [_tenant(bedrag="650.00")]
    payments = [_payment(bedrag="600.00")]

    results, _ = match_tenants_to_payments(tenants, payments, TOL)

    assert results[0].status == Status.TE_WEINIG


def test_te_veel_ontvangen():
    tenants = [_tenant(bedrag="650.00")]
    payments = [_payment(bedrag="675.00")]

    results, _ = match_tenants_to_payments(tenants, payments, TOL)

    assert results[0].status == Status.TE_VEEL


def test_matcht_op_iban_en_negeert_naam():
    tenant = _tenant(iban="NL91ABNA0417164300")
    payments = [
        _payment(bedrag="650.00", naam="Verkeerde Naam", iban="NL91ABNA0417164300"),
        _payment(bedrag="650.00", naam="Jan de Vries", iban="NL00ANDERBANK000001"),
    ]

    results, unmatched = match_tenants_to_payments([tenant], payments, TOL)

    assert results[0].status == Status.BETAALD
    assert len(unmatched) == 1  # de betaling met het verkeerde IBAN blijft ongekoppeld


def test_zoekwoord_heeft_voorrang_op_volledige_naam():
    tenant = _tenant(naam="Jan de Vries", zoekwoord="kamer3")
    payments = [_payment(bedrag="650.00", naam="J de Vries", omschrijving="kamer3 huur juli")]

    results, unmatched = match_tenants_to_payments([tenant], payments, TOL)

    assert results[0].status == Status.BETAALD
    assert unmatched == []


def test_betaling_wordt_niet_dubbel_toegekend():
    # "Vries" matcht ook op de betaling van "Jan de Vries" -> test dat de betaling
    # niet aan beide huurders tegelijk wordt toegekend.
    tenants = [_tenant(row=2, naam="Jan de Vries", bedrag="650.00"), _tenant(row=3, naam="Vries", bedrag="650.00")]
    payments = [_payment(bedrag="650.00", naam="Jan de Vries", omschrijving="huur")]

    results, unmatched = match_tenants_to_payments(tenants, payments, TOL)

    # Alleen de eerste huurder (sheet-volgorde) krijgt hem toegekend
    assert results[0].status == Status.BETAALD
    assert results[1].status == Status.NIET_ONTVANGEN
    assert unmatched == []
