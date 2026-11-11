"""Tests voor de pure aanwezigheid-/setback-logica."""
from __future__ import annotations

from datetime import datetime, timedelta

from kamerverhuur_scanner.aanwezigheid import (
    SetbackRegel, beslis_setback, detecteer_interactie, status,
)

NU = datetime(2026, 11, 8, 12, 0, 0)


# --- interactie-detectie ---

def test_interactie_bij_handmatige_wijziging():
    # huurder draait van 18 naar 21 (handmatig), wij hadden niets gezet
    assert detecteer_interactie(18.0, 21.0, "MANUAL", None) is True


def test_geen_interactie_bij_schema():
    assert detecteer_interactie(18.0, 21.0, None, None) is False


def test_geen_interactie_als_het_onze_eigen_zet_is():
    # wij zetten setback naar 15; de meting toont 15 -> geen interactie
    assert detecteer_interactie(20.0, 15.0, "TIMER", 15.0) is False


def test_geen_interactie_zonder_wijziging():
    assert detecteer_interactie(20.0, 20.0, "MANUAL", None) is False


def test_terugdraaien_boven_onze_setback_is_interactie():
    # wij zaten op 15, huurder draait naar 20 -> interactie (thuis)
    assert detecteer_interactie(15.0, 20.0, "MANUAL", 15.0) is True


# --- setback-beslissing ---

REGEL = SetbackRegel(actief=True, na_dagen=2, drempel=20.0, setback_temp=15.0)


def test_setback_uit_doet_niets():
    uit = SetbackRegel(actief=False)
    assert beslis_setback(uit, NU - timedelta(days=5), None, 21.0, NU).nieuw_doel is None


def test_start_setback_na_stille_periode():
    b = beslis_setback(REGEL, NU - timedelta(days=2, hours=1), None, 21.0, NU)
    assert b.nieuw_doel == 15.0
    assert b.setback_sinds == NU


def test_geen_setback_als_recent_actief():
    b = beslis_setback(REGEL, NU - timedelta(hours=5), None, 21.0, NU)
    assert b.nieuw_doel is None and b.setback_sinds is None


def test_geen_setback_als_kachel_al_laag():
    b = beslis_setback(REGEL, NU - timedelta(days=3), None, 16.0, NU)  # onder drempel
    assert b.nieuw_doel is None


def test_lopende_setback_wordt_vastgehouden():
    b = beslis_setback(REGEL, NU - timedelta(days=3), NU - timedelta(hours=2), 15.0, NU)
    assert b.nieuw_doel == 15.0


def test_zonder_interactiedata_geen_setback():
    assert beslis_setback(REGEL, None, None, 21.0, NU).nieuw_doel is None


# --- status ---

def test_status_thuis_bij_recente_interactie():
    assert status(NU - timedelta(hours=2), NU) == "thuis"


def test_status_afwezig_na_dagen_stil():
    assert status(NU - timedelta(days=3), NU, na_dagen=2) == "afwezig"


def test_status_onzeker_tussenin():
    assert status(NU - timedelta(hours=30), NU, na_dagen=2) == "onzeker"


def test_onbetrouwbare_kamer_nooit_afwezig():
    # tuinsleutel-kamer: hooguit onzeker, nooit hard afwezig
    assert status(NU - timedelta(days=5), NU, na_dagen=2, onbetrouwbaar=True) == "onzeker"


def test_bold_recent_maakt_thuis():
    assert status(None, NU, bold_recent=True) == "thuis"


def test_geen_data_is_onzeker():
    assert status(None, NU) == "onzeker"
