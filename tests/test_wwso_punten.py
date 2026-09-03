"""Validatie van de WWSO-puntentelling tegen de uitgewerkte voorbeelden en
waarderingstabellen uit het Huurcommissie-beleidsboek (versie juli 2026)."""
import math

import pytest

from rotterdam_scanner.wwso_punten import (
    GedeeldeKeuken,
    GedeeldeRuimte,
    GedeeldSanitair,
    GemeenschappelijkeBuitenruimte,
    Kamer,
    Woning,
    _energie_punten_per_m2,
    _gem_buitenruimte_punten_per_kamer,
    _keuken_basispunten,
    _keuken_punten_per_kamer,
    _rond_op_hele_punten,
    _rond_op_kwart,
    _sanitair_punten_per_kamer,
    _woz_punten,
    bereken_woning,
)


# --- Afrondingsregels (2.1.6 / 2.1.7) -------------------------------------
def test_afronding_kwart_naar_beneden():
    # Beleidsboek 2.1.6: 4,81 -> 4,75 (geen 1/8 verschil).
    assert _rond_op_kwart(4.81) == 4.75


def test_afronding_kwart_vanaf_achtste_omhoog():
    # Precies 1/8 boven de kwart rondt omhoog: 6,375 -> 6,50.
    assert _rond_op_kwart(6.375) == 6.50
    assert _rond_op_kwart(5.625) == 5.75


def test_eindsaldering_hele_punten():
    assert _rond_op_hele_punten(56.49) == 56
    assert _rond_op_hele_punten(56.50) == 57


# --- Rubriek 4: energieprestatie ------------------------------------------
def test_energielabel_punten_per_m2():
    assert _energie_punten_per_m2(Woning(kamers=[], energielabel="A")) == 0.65
    assert _energie_punten_per_m2(Woning(kamers=[], energielabel="B")) == 0.50
    assert _energie_punten_per_m2(Woning(kamers=[], energielabel="G")) == -0.15


def test_energielabel_voorbeeld_beleidsboek():
    # Beleidsboek p20: privé 20 m² + gedeelde woonkamer 40 m² over 4 kamers,
    # label A -> (20 + 10) x 0,65 = 19,50 punten.
    w = Woning(
        kamers=[Kamer(oppervlakte_m2=20.0) for _ in range(4)],
        energielabel="A",
        gedeelde_ruimten=[GedeeldeRuimte(oppervlakte_m2=40.0, is_vertrek=True)],
    )
    res = bereken_woning(w)
    assert res[0].punten_per_rubriek["energie"] == 19.50


def test_energie_bouwjaar_fallback():
    assert _energie_punten_per_m2(Woning(kamers=[], bouwjaar=2010)) == 0.65
    assert _energie_punten_per_m2(Woning(kamers=[], bouwjaar=1995)) == 0.35
    assert _energie_punten_per_m2(Woning(kamers=[], bouwjaar=1970)) == -0.15


# --- Rubriek 5: keuken -----------------------------------------------------
def test_keuken_basispunten():
    assert _keuken_basispunten(0.9, 6) == 0.0
    assert _keuken_basispunten(1.5, 6) == 4.0
    assert _keuken_basispunten(2.5, 6) == 7.0
    assert _keuken_basispunten(4.0, 6) == 10.0
    # 13 punten alleen bij >= 8 woonruimten met toegang.
    assert _keuken_basispunten(6.0, 6) == 10.0
    assert _keuken_basispunten(6.0, 8) == 13.0


def test_keuken_voorbeeld_beleidsboek():
    # Beleidsboek p24/25: aanrecht 2-3 m (7) + 3 punten extra, gedeeld door 4
    # kamers -> (7 + 3) / 4 = 2,5.
    keuken = GedeeldeKeuken(
        aanrecht_m=2.5,
        voorzieningen=["koelkast", "kookplaat_keramisch", "magnetron"],
    )
    assert _keuken_punten_per_kamer(keuken, 4) == pytest.approx(2.5)


def test_keuken_extra_afgetopt_op_basis():
    # Extra voorzieningen kunnen niet meer zijn dan de basispunten.
    keuken = GedeeldeKeuken(
        aanrecht_m=1.5,  # basis 4
        voorzieningen=["kookplaat_inductie", "koelkast", "oven_elektrisch",
                       "vaatwasser", "magnetron"],  # samen 5,25 -> afgetopt op 4
    )
    assert _keuken_punten_per_kamer(keuken, 1) == pytest.approx(8.0)  # 4 + 4


# --- Rubriek 6: sanitair ---------------------------------------------------
def test_sanitair_voorbeeld_beleidsboek():
    # Beleidsboek p29: bad/douche (6) gedeeld door 4 kamers -> 1,5.
    san = GedeeldSanitair(voorzieningen=["bad_douche"])
    assert _sanitair_punten_per_kamer(san, 4) == pytest.approx(1.5)


def test_sanitair_menkemaborg_waarden():
    # Douche 3, toilet-in-badkamer 2, wastafel 1 -> samen 6 over 6 kamers = 1,0.
    san = GedeeldSanitair(
        voorzieningen=["douche", "toilet_staand_badkamer", "wastafel"]
    )
    assert _sanitair_punten_per_kamer(san, 6) == pytest.approx(1.0)


# --- Rubriek 8: buitenruimte ----------------------------------------------
def test_prive_buitenruimte_voorbeeld():
    # Beleidsboek p32: 10 m² privé -> 2 + (10 x 0,35) = 5,5.
    w = Woning(kamers=[Kamer(oppervlakte_m2=12.0, prive_buitenruimte_m2=10.0)])
    res = bereken_woning(w)
    assert res[0].punten_per_rubriek["buitenruimte"] == 5.5


def test_gem_buitenruimte_menkemaborg():
    # 51 m² gedeelde buitenruimte, 1 adres, 6 kamers -> (0,75 x 51)/6 = 6,375
    # -> op kwart afgerond 6,50.
    bui = GemeenschappelijkeBuitenruimte(oppervlakte_m2=51.0)
    per_kamer = _gem_buitenruimte_punten_per_kamer(bui, 6)
    assert _rond_op_kwart(per_kamer) == 6.50


def test_buitenruimte_max_15():
    w = Woning(kamers=[Kamer(oppervlakte_m2=12.0, prive_buitenruimte_m2=100.0)])
    res = bereken_woning(w)
    assert res[0].punten_per_rubriek["buitenruimte"] == 15.0


# --- Rubriek 11: WOZ -------------------------------------------------------
def test_woz_banden():
    # >10% boven COROP-gemiddelde -> 14.
    w = Woning(kamers=[], woz_waarde=400_000, woz_oppervlakte_m2=90,
               corop_gemiddelde_woz_m2=3884)
    assert _woz_punten(w) == 14.0
    # Binnen +/-10% -> 12.
    w = Woning(kamers=[], woz_waarde=350_000, woz_oppervlakte_m2=90,
               corop_gemiddelde_woz_m2=3884)
    assert _woz_punten(w) == 12.0
    # >10% eronder -> 10.
    w = Woning(kamers=[], woz_waarde=295_000, woz_oppervlakte_m2=90,
               corop_gemiddelde_woz_m2=3884)
    assert _woz_punten(w) == 10.0


def test_woz_zonder_gegevens_is_minimum():
    assert _woz_punten(Woning(kamers=[])) == 10.0


# --- Rubriek 9: gedeelde overige ruimte -----------------------------------
def test_gedeelde_berging_menkemaborg():
    # Berging 6 m² als gemeenschappelijke overige ruimte over 6 kamers:
    # 6 x 0,75 / 6 = 0,75.
    w = Woning(
        kamers=[Kamer(oppervlakte_m2=12.0) for _ in range(6)],
        gedeelde_ruimten=[GedeeldeRuimte(oppervlakte_m2=6.0, is_vertrek=False)],
    )
    res = bereken_woning(w)
    # De oppervlakte-rubriek van een kamer = 12 (eigen) + 0,75 (berging-aandeel).
    assert res[0].punten_per_rubriek["oppervlakte"] == 12.75


# --- Integratie: einde tot maximale huur ----------------------------------
def test_volledige_berekening_geeft_huur():
    w = Woning(
        kamers=[Kamer(oppervlakte_m2=14.0, verwarmd=True) for _ in range(6)],
        energielabel="B",
        woz_waarde=295_000, woz_oppervlakte_m2=90, corop_gemiddelde_woz_m2=3884,
        gedeelde_keuken=GedeeldeKeuken(aanrecht_m=2.5, voorzieningen=["koelkast"]),
        gedeeld_sanitair=GedeeldSanitair(
            voorzieningen=["douche", "toilet_staand_badkamer", "wastafel"]),
        gemeenschappelijke_buitenruimte=GemeenschappelijkeBuitenruimte(
            oppervlakte_m2=51.0),
    )
    res = bereken_woning(w)
    assert len(res) == 6
    r = res[0]
    # Energie: label B (0,50) x 14 m² = 7,00.
    assert r.punten_per_rubriek["energie"] == 7.0
    # WOZ 10, sanitair 1,0, buitenruimte 6,50.
    assert r.punten_per_rubriek["woz"] == 10.0
    assert r.punten_per_rubriek["sanitair"] == 1.0
    assert r.punten_per_rubriek["buitenruimte"] == 6.50
    assert r.totaal_punten > 0
    assert r.max_kale_huur > 0
