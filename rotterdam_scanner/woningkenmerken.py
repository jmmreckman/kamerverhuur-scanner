"""Classificeert Move/Funda's objectDetailedType naar de grove tweedeling
appartement vs woonhuis (zelfde indeling die Funda hanteert), voor het
woningtype-filter op kansen.steenhub.nl.

Move levert per woning een gedetailleerd type (bv. BENEDENWONING, HERENHUIS).
Onbekende/nieuwe typen vallen bewust op None (= "onbekend") zodat ze niet in de
verkeerde bak belanden; breid dan de sets hieronder uit. De erfpacht/woonlagen/
VvE-kenmerken zitten niet op dit dossier-type en komen later via de detail-query.
"""
from __future__ import annotations

_APPARTEMENT = {
    "APPARTEMENT", "BENEDENWONING", "BOVENWONING", "BOVEN_WONING",
    "DUBBEL_BENEDENHUIS", "DUBBEL_BOVENHUIS", "BENEDEN_PLUS_WONING",
    "BENEDEN_EN_BOVENWONING", "BOVEN_EN_BENEDENWONING",
    "PORTIEKFLAT", "PORTIEKWONING", "GALERIJFLAT", "MAISONNETTE",
    "TUSSENVERDIEPING", "PENTHOUSE", "DAKAPPARTEMENT", "DAK_APPARTEMENT",
    "CORRIDORFLAT", "SERVICEFLAT", "BEL_ETAGE", "SOUTERRAIN",
}
_WOONHUIS = {
    "WOONHUIS", "EENGEZINSWONING", "HERENHUIS", "TUSSENWONING", "HOEKWONING",
    "EINDWONING", "GESCHAKELDE_WONING", "GESCHAKELDE_2_ONDER_1_KAPWONING",
    "TWEE_ONDER_EEN_KAPWONING", "HALFVRIJSTAANDE_WONING", "HALF_VRIJSTAAND",
    "VRIJSTAANDE_WONING", "VRIJSTAAND", "BUNGALOW", "VILLA", "LANDHUIS",
    "LANDGOED", "BOERDERIJ", "WOONBOERDERIJ", "GRACHTENPAND", "DIJKWONING",
    "PATIOWONING", "SPLITLEVELWONING", "VERSPRINGEND_WONING",
}


def classificeer_woningtype(detail: str | None) -> str | None:
    """'appartement' / 'woonhuis' / None (onbekend) uit het Move-objectDetailedType."""
    if not detail:
        return None
    sleutel = detail.strip().upper()
    if sleutel in _APPARTEMENT:
        return "appartement"
    if sleutel in _WOONHUIS:
        return "woonhuis"
    return None


def mooi_woningtype(detail: str | None) -> str | None:
    """Leesbaar label voor het ruwe type, bv. BOVEN_WONING -> 'Boven woning'."""
    if not detail:
        return None
    return detail.strip().replace("_", " ").capitalize()
