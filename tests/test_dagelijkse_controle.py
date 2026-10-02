"""Tests voor de planning-logica van het automatische-controle-script (draait
elk uur op het hele uur, Nederlandse tijd, zonder losse cron-daemon)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.dagelijkse_controle import _seconden_tot_volgende_run

_TZ = ZoneInfo("Europe/Amsterdam")


def test_wacht_tot_eerstvolgende_hele_uur():
    nu = datetime(2026, 7, 8, 14, 23, tzinfo=_TZ)
    wachttijd = _seconden_tot_volgende_run(nu)
    assert wachttijd == 37 * 60


def test_vlak_voor_het_hele_uur_wacht_bijna_niets():
    nu = datetime(2026, 7, 8, 14, 59, 30, tzinfo=_TZ)
    wachttijd = _seconden_tot_volgende_run(nu)
    assert wachttijd == 30


def test_precies_op_het_hele_uur_wacht_tot_het_volgende():
    nu = datetime(2026, 7, 8, 6, 0, tzinfo=_TZ)
    wachttijd = _seconden_tot_volgende_run(nu)
    assert wachttijd == 3600


def test_om_middernacht_wacht_tot_een_uur():
    nu = datetime(2026, 7, 8, 0, 0, 1, tzinfo=_TZ)
    wachttijd = _seconden_tot_volgende_run(nu)
    assert wachttijd == 3600 - 1
