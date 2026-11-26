"""Tests voor de pure terugschakel-regel-engine."""
from __future__ import annotations

from datetime import datetime, timedelta

from kamerverhuur_scanner.verwarming_regels import Regel, beslis, sensor_ok

NU = datetime(2026, 11, 7, 12, 0, 0)
REGEL = Regel(max_temp=25, stap=1, interval_min=15, vloer_temp=20, na_uren=3, nacht_temp=18)


def test_sensor_ok_grenzen():
    assert sensor_ok(20.0)
    assert not sensor_ok(None)
    assert not sensor_ok(31.0)   # sensor in de zon o.i.d.
    assert not sensor_ok(4.0)


def test_onder_plafond_doet_niets():
    b = beslis(REGEL, 20.0, NU, None, None)
    assert b.nieuw_doel is None and b.actief_sinds is None


def test_op_plafond_start_afbouw_zonder_meteen_te_wijzigen():
    b = beslis(REGEL, 25.0, NU, None, None)
    assert b.nieuw_doel is None          # staat al op 25, niets te zetten
    assert b.actief_sinds == NU          # maar afbouw is nu gestart
    assert b.laatste_doel == 25


def test_boven_plafond_wordt_meteen_gecapt():
    b = beslis(REGEL, 26.5, NU, None, None)
    assert b.nieuw_doel == 25
    assert b.actief_sinds == NU


def test_na_een_interval_een_graad_eraf():
    sinds = NU - timedelta(minutes=15)
    b = beslis(REGEL, 25.0, NU, sinds, 25.0)
    assert b.nieuw_doel == 24
    assert b.actief_sinds == sinds       # zelfde startmoment vastgehouden


def test_na_drie_kwartier_drie_graden_eraf():
    sinds = NU - timedelta(minutes=45)
    b = beslis(REGEL, 25.0, NU, sinds, 25.0)
    assert b.nieuw_doel == 22


def test_klemt_op_de_vloer():
    sinds = NU - timedelta(minutes=120)   # zou 25-8=17 zijn, maar vloer is 20
    b = beslis(REGEL, 23.0, NU, sinds, 23.0)
    assert b.nieuw_doel == 20


def test_na_na_uren_naar_nacht_temp():
    sinds = NU - timedelta(hours=3)
    b = beslis(REGEL, 20.0, NU, sinds, 20.0)
    assert b.nieuw_doel == 18             # na 3 uur hoog -> nachttemp


def test_huurder_zelf_lager_laat_regel_los():
    sinds = NU - timedelta(minutes=15)
    # wij zaten op 24, huurder draait naar 21 (lager) -> loslaten
    b = beslis(REGEL, 21.0, NU, sinds, 24.0)
    assert b.nieuw_doel is None
    assert b.actief_sinds is None         # status gewist


def test_geen_dubbele_schrijf_als_doel_gelijk_blijft():
    sinds = NU - timedelta(minutes=15)
    # doel zou 24 zijn, en we zitten al op 24 -> niets sturen, status vasthouden
    b = beslis(REGEL, 24.0, NU, sinds, 24.0)
    assert b.nieuw_doel is None
    assert b.actief_sinds == sinds


def test_kamer_uit_wist_status():
    b = beslis(REGEL, None, NU, NU - timedelta(minutes=30), 23.0)
    assert b.nieuw_doel is None and b.actief_sinds is None


def test_ongeldige_regel_doet_niets():
    kapot = Regel(max_temp=20, stap=1, interval_min=15, vloer_temp=25, na_uren=3, nacht_temp=18)
    assert beslis(kapot, 25.0, NU, None, None).nieuw_doel is None


def test_regel_uit_row_met_lege_velden_valt_terug_op_standaard():
    row = {"max_temp": None, "stap": None, "interval_min": None,
           "vloer_temp": None, "na_uren": None, "nacht_temp": None}
    r = Regel.uit_row(row)
    assert r.max_temp == 25 and r.vloer_temp == 20 and r.interval_min == 15
