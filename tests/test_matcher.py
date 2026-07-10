from datetime import date
from decimal import Decimal

from kamerverhuur_scanner.matcher import _verwerk_maand, match_tenants_to_payments, openstaand_tekort_uit_geschiedenis
from kamerverhuur_scanner.models import HistorieRegel, Payment, Status, Tenant

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


def test_matcht_op_iban_ook_als_naam_niet_overeenkomt():
    tenant = _tenant(iban="NL91ABNA0417164300")
    payments = [_payment(bedrag="650.00", naam="Verkeerde Naam", iban="NL91ABNA0417164300", omschrijving="salaris")]

    results, unmatched = match_tenants_to_payments([tenant], payments, TOL)

    assert results[0].status == Status.BETAALD
    assert unmatched == []


def test_iban_mismatch_valt_terug_op_naam_matching():
    # Regressietest: een IBAN op de sheet dat niet (meer) klopt mag geen
    # matches blokkeren die anders wel op naam zouden lukken - anders wordt
    # een kamer erger af na het invullen van een IBAN dan ervoor.
    tenant = _tenant(iban="NL91ABNA0417164300")
    payments = [_payment(bedrag="650.00", naam="Jan de Vries", iban="NL00ANDERBANK000001")]

    results, unmatched = match_tenants_to_payments([tenant], payments, TOL)

    assert results[0].status == Status.BETAALD
    assert unmatched == []


def test_zoekwoord_heeft_voorrang_op_volledige_naam():
    tenant = _tenant(naam="Jan de Vries", zoekwoord="kamer3")
    payments = [_payment(bedrag="650.00", naam="J de Vries", omschrijving="kamer3 huur juli")]

    results, unmatched = match_tenants_to_payments([tenant], payments, TOL)

    assert results[0].status == Status.BETAALD
    assert unmatched == []


def test_matcht_op_voornaam_als_ouder_betaalt():
    # De moeder maakt over, maar de voornaam van de huurder staat in de omschrijving.
    tenant = _tenant(naam="Ewen Jayad", bedrag="785.00")
    payments = [_payment(bedrag="785.00", naam="Morgane Dubois", omschrijving="Huur Ewen juli")]

    results, unmatched = match_tenants_to_payments([tenant], payments, TOL)

    assert results[0].status == Status.BETAALD
    assert unmatched == []


def test_matcht_op_deel_van_koppelnaam():
    # Achternaam komt hier expres niet voor, alleen een deel van de koppelnaam.
    tenant = _tenant(naam="Stefania-Teodora Olteanu", bedrag="745.00")
    payments = [_payment(bedrag="745.00", naam="Andere Afzender", omschrijving="teodora huur juli")]

    results, unmatched = match_tenants_to_payments([tenant], payments, TOL)

    assert results[0].status == Status.BETAALD
    assert unmatched == []


def test_ruimere_tolerantie_kamer_accepteert_afwijking_binnen_10_procent():
    # De instapmaand (pro-rata huur + borg) wijkt vaker een paar euro af door
    # afrondingsverschillen (bv. een dag verschil in de ingangsdatum) - voor
    # zo'n kamer geldt daarom een tolerantie van 10% i.p.v. bijna exact.
    tenant = _tenant(kamer="1", bedrag="1471.83")
    payments = [_payment(bedrag="1447.00")]  # 1,7% minder dan verwacht

    results, _ = match_tenants_to_payments([tenant], payments, TOL, {"1"})

    assert results[0].status == Status.BETAALD


def test_ruimere_tolerantie_geldt_niet_voor_andere_kamers():
    tenant = _tenant(kamer="2", bedrag="1471.83")
    payments = [_payment(bedrag="1447.00")]

    results, _ = match_tenants_to_payments([tenant], payments, TOL, {"1"})

    assert results[0].status == Status.TE_WEINIG


def test_ruimere_tolerantie_accepteert_geen_afwijking_boven_10_procent():
    tenant = _tenant(kamer="1", bedrag="1471.83")
    payments = [_payment(bedrag="1300.00")]  # ruim 10% minder dan verwacht

    results, _ = match_tenants_to_payments([tenant], payments, TOL, {"1"})

    assert results[0].status == Status.TE_WEINIG


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


# --- inhaalbetaling lost eerst een openstaande achterstand af ---

def test_inhaalbetaling_lost_eerst_openstaand_tekort_af_dan_pas_deze_maand():
    # Henri miste vorige maand (745 verwacht, niks ontvangen) en betaalt deze
    # maand in één keer 2x de huur (1490) - dat mag niet als "te veel
    # ontvangen" verschijnen, want hij is daarmee gewoon weer bij.
    tenant = _tenant(bedrag="745.00")
    payments = [_payment(bedrag="1490.00")]

    results, _ = match_tenants_to_payments([tenant], payments, TOL, openstaand_tekort={"1": Decimal("745.00")})

    assert results[0].status == Status.BETAALD


def test_overschot_na_aflossen_tekort_telt_alsnog_als_te_veel():
    tenant = _tenant(bedrag="745.00")
    payments = [_payment(bedrag="1600.00")]  # 745 tekort aflossen + 110 te veel

    results, _ = match_tenants_to_payments([tenant], payments, TOL, openstaand_tekort={"1": Decimal("745.00")})

    assert results[0].status == Status.TE_VEEL


def test_betaling_die_zelfs_deze_maand_niet_dekt_blijft_te_weinig_ondanks_tekort():
    # Deze maand zelf wordt niet eens gehaald - dan is er niks om het oude
    # tekort mee af te lossen, en telt het gewoon als "te weinig" voor deze
    # maand (het openstaande tekort wordt alleen maar groter).
    tenant = _tenant(bedrag="745.00")
    payments = [_payment(bedrag="700.00")]

    results, _ = match_tenants_to_payments([tenant], payments, TOL, openstaand_tekort={"1": Decimal("745.00")})

    assert results[0].status == Status.TE_WEINIG


def test_overschot_dat_deze_maand_dekt_plus_deel_van_tekort_telt_als_betaald():
    # De huidige maand zelf is gedekt (745) en de resterende 55 lost een deel
    # van de oude achterstand af - deze maand mag dan gewoon "Betaald" tonen,
    # ook al is de oude achterstand nog niet helemaal weg.
    tenant = _tenant(bedrag="745.00")
    payments = [_payment(bedrag="800.00")]

    results, _ = match_tenants_to_payments([tenant], payments, TOL, openstaand_tekort={"1": Decimal("745.00")})

    assert results[0].status == Status.BETAALD


def test_geen_openstaand_tekort_gedraagt_zich_als_voorheen():
    tenant = _tenant(bedrag="745.00")
    payments = [_payment(bedrag="745.00")]

    results, _ = match_tenants_to_payments([tenant], payments, TOL, openstaand_tekort={"1": Decimal("0")})

    assert results[0].status == Status.BETAALD


def test_verwerk_maand_zonder_tekort_gedraagt_zich_als_bepaal_status():
    status, nieuw_tekort = _verwerk_maand(Decimal("650.00"), Decimal("650.00"), TOL, Decimal("0"), Decimal("0"))
    assert status == Status.BETAALD
    assert nieuw_tekort == Decimal("0")


def test_verwerk_maand_bouwt_tekort_op_bij_niet_ontvangen():
    status, nieuw_tekort = _verwerk_maand(Decimal("0"), Decimal("650.00"), TOL, Decimal("0"), Decimal("0"))
    assert status == Status.NIET_ONTVANGEN
    assert nieuw_tekort == Decimal("650.00")


# --- openstaand_tekort_uit_geschiedenis ---

def _regel(maand, verwacht="745.00", ontvangen="0.00", status=Status.NIET_ONTVANGEN):
    return HistorieRegel(
        maand=maand, kamer="1", huurder="Henri",
        verwacht_bedrag=Decimal(verwacht), ontvangen_bedrag=Decimal(ontvangen), status=status,
    )


def test_tekort_som_van_opeenvolgende_openstaande_maanden():
    geschiedenis = [
        _regel("2026-05", status=Status.BETAALD, ontvangen="745.00"),
        _regel("2026-06", status=Status.NIET_ONTVANGEN, ontvangen="0.00"),
    ]
    assert openstaand_tekort_uit_geschiedenis(geschiedenis, "2026-07") == Decimal("745.00")


def test_tekort_stopt_bij_eerste_volledig_betaalde_maand_terugkijkend():
    geschiedenis = [
        _regel("2026-04", status=Status.NIET_ONTVANGEN, ontvangen="0.00"),  # al lang geleden opgelost/irrelevant
        _regel("2026-05", status=Status.BETAALD, ontvangen="745.00"),
        _regel("2026-06", status=Status.TE_WEINIG, ontvangen="200.00"),
    ]
    assert openstaand_tekort_uit_geschiedenis(geschiedenis, "2026-07") == Decimal("545.00")


def test_geen_tekort_als_laatste_maand_al_betaald_was():
    geschiedenis = [_regel("2026-06", status=Status.BETAALD, ontvangen="745.00")]
    assert openstaand_tekort_uit_geschiedenis(geschiedenis, "2026-07") == Decimal("0")


def test_tekort_negeert_de_huidige_maand_zelf():
    geschiedenis = [_regel("2026-07", status=Status.NIET_ONTVANGEN, ontvangen="0.00")]
    assert openstaand_tekort_uit_geschiedenis(geschiedenis, "2026-07") == Decimal("0")
