"""Tests voor de tijdsberekening in de Apify-scheduler-scripts - alleen de
pure datum/tijd-functie, niet de oneindige while-lus zelf (net als bij het
bestaande scripts/dagelijkse_scan.py, dat om dezelfde reden ook ongetest is)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts import dagelijkse_apify_scan, wekelijkse_apify_scan

_TZ = ZoneInfo("Europe/Amsterdam")


# --- dagelijkse_apify_scan (elke dag 08:00) ---


def test_dagelijks_voor_8_uur_wacht_tot_vandaag_8_uur():
    nu = datetime(2026, 7, 20, 6, 0, tzinfo=_TZ)
    wachttijd = dagelijkse_apify_scan._seconden_tot_volgende_run(nu)
    assert wachttijd == 2 * 3600


def test_dagelijks_na_8_uur_wacht_tot_morgen_8_uur():
    nu = datetime(2026, 7, 20, 14, 30, tzinfo=_TZ)
    wachttijd = dagelijkse_apify_scan._seconden_tot_volgende_run(nu)
    assert wachttijd == (17 * 3600) + (30 * 60)


def test_dagelijks_precies_om_8_uur_wacht_tot_morgen():
    nu = datetime(2026, 7, 20, 8, 0, tzinfo=_TZ)
    wachttijd = dagelijkse_apify_scan._seconden_tot_volgende_run(nu)
    assert wachttijd == 24 * 3600


# --- wekelijkse_apify_scan (elke maandag 07:00) ---


def test_wekelijks_op_maandagochtend_voor_7_uur_wacht_tot_diezelfde_ochtend():
    nu = datetime(2026, 7, 20, 5, 0, tzinfo=_TZ)  # 20 juli 2026 is een maandag
    assert nu.weekday() == 0
    wachttijd = wekelijkse_apify_scan._seconden_tot_volgende_run(nu)
    assert wachttijd == 2 * 3600


def test_wekelijks_op_maandagochtend_na_7_uur_wacht_tot_volgende_maandag():
    nu = datetime(2026, 7, 20, 9, 0, tzinfo=_TZ)
    wachttijd = wekelijkse_apify_scan._seconden_tot_volgende_run(nu)
    assert wachttijd == (7 * 24 * 3600) - (2 * 3600)


def test_wekelijks_midden_in_de_week_wacht_tot_eerstvolgende_maandag():
    nu = datetime(2026, 7, 22, 12, 0, tzinfo=_TZ)  # woensdag
    assert nu.weekday() == 2
    wachttijd = wekelijkse_apify_scan._seconden_tot_volgende_run(nu)
    verwachte_maandag = datetime(2026, 7, 27, 7, 0, tzinfo=_TZ)
    assert wachttijd == (verwachte_maandag - nu).total_seconds()


def test_wekelijks_op_zondag_wacht_tot_maandagochtend_erna():
    nu = datetime(2026, 7, 26, 23, 0, tzinfo=_TZ)  # zondag
    assert nu.weekday() == 6
    wachttijd = wekelijkse_apify_scan._seconden_tot_volgende_run(nu)
    verwachte_maandag = datetime(2026, 7, 27, 7, 0, tzinfo=_TZ)
    assert wachttijd == (verwachte_maandag - nu).total_seconds()
