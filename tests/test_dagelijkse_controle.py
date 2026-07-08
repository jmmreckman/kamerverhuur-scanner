"""Tests voor de planning-logica van het dagelijkse-controle-script (draait
elke ochtend om 06:00 Nederlandse tijd zonder losse cron-daemon)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.dagelijkse_controle import _seconden_tot_volgende_run

_TZ = ZoneInfo("Europe/Amsterdam")


def test_voor_zessen_wacht_tot_vandaag_zes_uur():
    nu = datetime(2026, 7, 8, 3, 0, tzinfo=_TZ)
    wachttijd = _seconden_tot_volgende_run(nu)
    assert wachttijd == 3 * 3600


def test_na_zessen_wacht_tot_morgen_zes_uur():
    nu = datetime(2026, 7, 8, 14, 30, tzinfo=_TZ)
    wachttijd = _seconden_tot_volgende_run(nu)
    verwacht = (24 - 14.5 + 6) * 3600
    assert wachttijd == verwacht


def test_precies_zes_uur_wacht_tot_morgen():
    nu = datetime(2026, 7, 8, 6, 0, tzinfo=_TZ)
    wachttijd = _seconden_tot_volgende_run(nu)
    assert wachttijd == 24 * 3600
