"""Tests voor de tijdsberekening in scripts/dagelijkse_beschikbaarheid_check.py -
alleen de pure datum/tijd-functie, niet de oneindige while-lus zelf (net als bij
scripts/dagelijkse_scan.py)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts import dagelijkse_beschikbaarheid_check

_TZ = ZoneInfo("Europe/Amsterdam")


def test_voor_8_uur_wacht_tot_vandaag_8_uur():
    nu = datetime(2026, 7, 20, 6, 0, tzinfo=_TZ)
    wachttijd = dagelijkse_beschikbaarheid_check._seconden_tot_volgende_run(nu)
    assert wachttijd == 2 * 3600


def test_na_8_uur_wacht_tot_morgen_8_uur():
    nu = datetime(2026, 7, 20, 14, 30, tzinfo=_TZ)
    wachttijd = dagelijkse_beschikbaarheid_check._seconden_tot_volgende_run(nu)
    assert wachttijd == (17 * 3600) + (30 * 60)


def test_precies_om_8_uur_wacht_tot_morgen():
    nu = datetime(2026, 7, 20, 8, 0, tzinfo=_TZ)
    wachttijd = dagelijkse_beschikbaarheid_check._seconden_tot_volgende_run(nu)
    assert wachttijd == 24 * 3600
