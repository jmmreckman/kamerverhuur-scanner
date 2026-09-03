"""Tests voor de WWSO punten->euro-tabel (Bijlage 2 beleidsboek, per 1-1-2026).
De ijkpunten komen 1-op-1 uit de echte huurprijschecks van Menkemaborgstraat 6."""
import pytest

from rotterdam_scanner.wwso_huur import max_huur_bij_punten


def test_reproduceert_de_echte_huurprijschecks():
    # Exact zoals de Huurcommissie-Huurprijscheck teruggaf per kamer.
    assert max_huur_bij_punten(53) == 539.99
    assert max_huur_bij_punten(58) == 590.95
    assert max_huur_bij_punten(63) == 627.09
    assert max_huur_bij_punten(64) == 632.41
    assert max_huur_bij_punten(65) == 637.63
    assert max_huur_bij_punten(66) == 642.97


def test_randen_van_de_tabel():
    assert max_huur_bij_punten(0) == 0.0
    assert max_huur_bij_punten(1) == 10.33
    assert max_huur_bij_punten(250) == 1613.63


def test_boven_250_punten_lineair_doorgetrokken():
    # 2.1.8: elk punt boven 250 telt als het verschil tussen 249 en 250 punten.
    stap = round(max_huur_bij_punten(250) - max_huur_bij_punten(249), 2)
    assert max_huur_bij_punten(251) == round(1613.63 + stap, 2)
    assert max_huur_bij_punten(260) == round(1613.63 + 10 * stap, 2)


def test_negatief_geeft_fout():
    with pytest.raises(ValueError):
        max_huur_bij_punten(-1)
