"""WWSO-huurberekening: van punten naar de maximale (kale) huurprijs voor
onzelfstandige woonruimte.

De punten->euro-tabel komt 1-op-1 uit Bijlage 2 van het "Beleidsboek waardering
onzelfstandige woonruimte" (per 1 januari 2026) van de Huurcommissie
(wwso_huurprijstabel_2026.TABEL, 0 t/m 250 punten). Boven de 250 punten geldt de
rekenregel uit 2.1.8: elk punt boven 250 telt als het verschil tussen de bedragen
bij 249 en 250 punten, opgeteld bij het bedrag bij 250.

De puntentelling zelf (oppervlakte, keuken, sanitair, WOZ, energielabel, ...) zit
in wwso_punten.py; deze module doet alleen de laatste stap punten -> euro.
"""
from __future__ import annotations

from .wwso_huurprijstabel_2026 import TABEL


def max_huur_bij_punten(punten: int) -> float:
    """Maximale kale huurprijs (€/maand) bij een gegeven, op hele punten afgerond
    puntentotaal. Volgt Bijlage 2 t/m 250 punten en de >250-rekenregel daarboven."""
    if punten < 0:
        raise ValueError("punten kan niet negatief zijn")
    if punten <= 250:
        return TABEL[punten]
    # 2.1.8: elk punt boven 250 = (bedrag[250] - bedrag[249]) erbij.
    stap = round(TABEL[250] - TABEL[249], 2)
    return round(TABEL[250] + (punten - 250) * stap, 2)
