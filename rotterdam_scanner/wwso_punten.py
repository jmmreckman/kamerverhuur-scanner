"""Puntentelling voor onzelfstandige woonruimte (WWSO), volgens het
"Beleidsboek waardering onzelfstandige woonruimte" (versie juli 2026) van de
Huurcommissie.

De berekening gaat uit van één woonadres met meerdere onzelfstandige
woonruimten (kamers). Gedeelde voorzieningen (keuken, sanitair, buitenruimte,
gemeenschappelijke vertrekken, ...) worden per rubriek gedeeld over het aantal
kamers dat er toegang en gebruiksrecht toe heeft; privévoorzieningen tellen
volledig voor de betreffende kamer.

De uitkomst per kamer is een puntentotaal; via wwso_huur.max_huur_bij_punten
volgt daaruit de maximale kale huurprijs.

Deze module berekent alleen de punten. De laatste stap (punten -> euro) staat in
wwso_huur.py, de punten->euro-tabel in wwso_huurprijstabel_2026.py.

Belangrijkste rekenregels (hoofdstuk 2 van het beleidsboek):
 - Rubriek 1 (vertrekken): 1 punt per m².
 - Rubriek 2 (overige ruimten): 0,75 punt per m².
 - Rubriek 3 (verwarming): 2 punten per verwarmd vertrek; 1 punt per verwarmde
   overige/verkeersruimte (samen max 4).
 - Rubriek 4 (energieprestatie): punten/m² x (privé + toegerekende gedeelde
   vertrek-m²), afhankelijk van het energielabel of het bouwjaar.
 - Rubriek 5 (keuken): basispunten op aanrechtlengte + extra voorzieningen
   (afgetopt op de basispunten), gedeeld door het aantal kamers.
 - Rubriek 6 (sanitair): punten per voorziening, gedeeld door het aantal kamers
   bij gedeeld gebruik.
 - Rubriek 8 (buitenruimte): privé 2 punten + 0,35/m²; gemeenschappelijk
   0,75/m² gedeeld door adressen en kamers (samen max 15).
 - Rubriek 9 (gemeenschappelijke binnenruimten): 1/m² (vertrek) of 0,75/m²
   (overige), gedeeld door adressen en kamers.
 - Rubriek 11 (WOZ): 10/12/14 punten op basis van de WOZ-waarde/m² t.o.v. het
   COROP-gemiddelde.
 - Afronding: per rubriek op 0,25 punt (vanaf 1/8 omhoog), eindtotaal op hele
   punten (vanaf 0,5 omhoog). Boven 250 punten: zie wwso_huur.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# --- Energielabel -> punten per m² (Bijlage/rubriek 4, NTA 8800 vanaf 1-1-2021) --
ENERGIELABEL_PUNTEN: dict[str, float] = {
    "A++++": 1.0,
    "A+++": 0.95,
    "A++": 0.85,
    "A+": 0.75,
    "A": 0.65,
    "B": 0.50,
    "C": 0.35,
    "D": 0.20,
    "E": -0.05,
    "F": -0.10,
    "G": -0.15,
}

# --- Bouwjaar -> punten per m² (rubriek 4, als geen geldig label bekend is) -----
_BOUWJAAR_PUNTEN: list[tuple[int, float]] = [
    (2002, 0.65),   # 2002 en later
    (2000, 0.50),   # 2000 t/m 2001
    (1992, 0.35),   # 1992 t/m 1999
    (1984, 0.20),   # 1984 t/m 1991
    (1979, -0.05),  # 1979 t/m 1983
    (1977, -0.10),  # 1977 t/m 1978
    (0, -0.15),     # 1976 of ouder
]

# --- Keuken: aanrechtlengte -> basispunten (rubriek 5) -------------------------
def _keuken_basispunten(aanrecht_m: float, aantal_woonruimten_toegang: int) -> float:
    """Basispunten voor de aanrechtlengte. 13 punten (>5 m) alleen bij minstens
    8 onzelfstandige woonruimten met toegang en gebruiksrecht."""
    if aanrecht_m < 1:
        return 0.0
    if aanrecht_m < 2:
        return 4.0
    if aanrecht_m < 3:
        return 7.0
    if aanrecht_m <= 5:
        return 10.0
    return 13.0 if aantal_woonruimten_toegang >= 8 else 10.0


# Extra keukenvoorzieningen (rubriek 5) -> punten.
KEUKEN_VOORZIENINGEN: dict[str, float] = {
    "afzuiginstallatie": 0.75,
    "kookplaat_inductie": 1.75,
    "kookplaat_keramisch": 1.0,
    "kookplaat_gas": 0.50,
    "koelkast": 1.0,
    "vrieskast": 0.75,
    "oven_elektrisch": 1.0,
    "oven_gas": 0.50,
    "magnetron": 1.0,
    "vaatwasser": 1.50,
    "eenhandsmengkraan": 0.25,
    "thermostatische_mengkraan": 0.50,
    "kokend_water": 0.50,
}

# Sanitaire basisvoorzieningen (rubriek 6) -> punten.
SANITAIR_VOORZIENINGEN: dict[str, float] = {
    "toilet_staand_toiletruimte": 3.0,
    "toilet_staand_badkamer": 2.0,
    "toilet_hangend_toiletruimte": 3.75,
    "toilet_hangend_badkamer": 2.75,
    "wastafel": 1.0,
    "meerpersoonswastafel": 1.50,
    "douche": 3.0,
    "bad": 5.0,
    "bad_douche": 6.0,
}


def _rond_op_kwart(punten: float) -> float:
    """Afronden op 0,25 punt; vanaf 1/8 (0,125) punt naar boven (rubriek-afronding,
    2.1.6)."""
    return round(math.floor(punten / 0.25 + 0.5 + 1e-9) * 0.25, 2)


def _rond_op_hele_punten(punten: float) -> int:
    """Eindsaldering op hele punten; vanaf 0,5 naar boven (2.1.7)."""
    return int(math.floor(punten + 0.5 + 1e-9))


def _rond_m2(m2: float) -> int:
    """Oppervlakte afronden op hele m²; 0,50 omhoog, 0,49 of lager omlaag
    (2.1.1.1)."""
    return int(math.floor(m2 + 0.5 + 1e-9))


# ---------------------------------------------------------------------------
# Invoermodel
# ---------------------------------------------------------------------------
@dataclass
class Kamer:
    """Eén onzelfstandige woonruimte (privégegevens van de huurder)."""
    oppervlakte_m2: float                 # privévertrek (de kamer zelf)
    verwarmd: bool = True                 # eigen vertrek verwarmd (2 punten)
    prive_overige_m2: float = 0.0         # eigen berging/bijkeuken e.d. (0,75/m²)
    prive_buitenruimte_m2: float = 0.0    # eigen balkon/tuin (2 + 0,35/m²)
    # Optionele eigen (niet-gedeelde) keuken/sanitair op de kamer:
    prive_sanitair: list[str] = field(default_factory=list)


@dataclass
class GedeeldeKeuken:
    aanrecht_m: float
    voorzieningen: list[str] = field(default_factory=list)
    extra_kastruimte_60cm: int = 0        # aantal extra kaststukken van 60 cm
    aantal_kamers_toegang: int | None = None  # None = alle kamers op het adres


@dataclass
class GedeeldSanitair:
    voorzieningen: list[str] = field(default_factory=list)
    aantal_kamers_toegang: int | None = None


@dataclass
class GedeeldeRuimte:
    """Gemeenschappelijk vertrek of overige ruimte (rubriek 9)."""
    oppervlakte_m2: float
    is_vertrek: bool = True               # True: 1/m², False (overige): 0,75/m²
    verwarmd: bool = False
    aantal_adressen: int = 1              # adressen in woongebouw met toegang
    aantal_kamers_toegang: int | None = None


@dataclass
class GemeenschappelijkeBuitenruimte:
    oppervlakte_m2: float
    aantal_adressen: int = 1
    aantal_kamers_toegang: int | None = None


@dataclass
class Woning:
    """Een woonadres met onzelfstandige woonruimten (kamers)."""
    kamers: list[Kamer]
    energielabel: str | None = None       # bv. "B"; None => bouwjaar gebruiken
    bouwjaar: int | None = None
    woz_waarde: float | None = None       # WOZ-waarde van het hele adres
    woz_oppervlakte_m2: float | None = None  # gebruiksoppervlakte hele adres
    corop_gemiddelde_woz_m2: float | None = None  # Bijlage 1, regio
    gedeelde_keuken: GedeeldeKeuken | None = None
    gedeeld_sanitair: GedeeldSanitair | None = None
    gedeelde_ruimten: list[GedeeldeRuimte] = field(default_factory=list)
    gemeenschappelijke_buitenruimte: GemeenschappelijkeBuitenruimte | None = None


@dataclass
class KamerResultaat:
    kamer: Kamer
    punten_per_rubriek: dict[str, float]
    totaal_punten: int
    max_kale_huur: float


# ---------------------------------------------------------------------------
# Losse rubriek-berekeningen (elk geeft ruwe, nog niet op 0,25 afgeronde punten)
# ---------------------------------------------------------------------------
def _energie_punten_per_m2(woning: Woning) -> float:
    if woning.energielabel:
        label = woning.energielabel.strip().upper()
        if label not in ENERGIELABEL_PUNTEN:
            raise ValueError(f"onbekend energielabel: {woning.energielabel!r}")
        return ENERGIELABEL_PUNTEN[label]
    if woning.bouwjaar is not None:
        for vanaf, punten in _BOUWJAAR_PUNTEN:
            if woning.bouwjaar >= vanaf:
                return punten
    # Geen label én geen bouwjaar bekend: neem de ongunstigste waardering.
    return -0.15


def _woz_punten(woning: Woning) -> float:
    """Rubriek 11: 10/12/14 punten op basis van WOZ-waarde/m² t.o.v. het
    COROP-gemiddelde. Zonder gegevens geldt de minimumwaardering (10)."""
    if not (woning.woz_waarde and woning.woz_oppervlakte_m2 and woning.corop_gemiddelde_woz_m2):
        return 10.0
    woz_per_m2 = woning.woz_waarde / woning.woz_oppervlakte_m2
    verhouding = woz_per_m2 / woning.corop_gemiddelde_woz_m2
    if verhouding > 1.10:
        return 14.0
    if verhouding < 0.90:
        return 10.0
    return 12.0


def _keuken_punten_per_kamer(keuken: GedeeldeKeuken, aantal_kamers: int) -> float:
    delen = keuken.aantal_kamers_toegang or aantal_kamers
    basis = _keuken_basispunten(keuken.aanrecht_m, delen)
    if basis == 0:
        return 0.0  # zonder basisvoorzieningen geen keukenpunten (ook geen extra)
    extra = sum(KEUKEN_VOORZIENINGEN[v] for v in keuken.voorzieningen)
    extra += keuken.extra_kastruimte_60cm * 0.75  # extra kastruimte, 0,75 per 60 cm
    extra = min(extra, basis)  # extra afgetopt op de basispunten
    return (basis + extra) / delen


def _sanitair_punten_per_kamer(sanitair: GedeeldSanitair, aantal_kamers: int) -> float:
    delen = sanitair.aantal_kamers_toegang or aantal_kamers
    totaal = sum(SANITAIR_VOORZIENINGEN[v] for v in sanitair.voorzieningen)
    return totaal / delen


def _prive_sanitair_punten(voorzieningen: list[str]) -> float:
    return sum(SANITAIR_VOORZIENINGEN[v] for v in voorzieningen)


def _gedeelde_ruimte_punten_per_kamer(ruimte: GedeeldeRuimte, aantal_kamers: int) -> tuple[float, float]:
    """Geeft (oppervlaktepunten, verwarmingspunten) per kamer voor een
    gemeenschappelijke binnenruimte (rubriek 9 + 3)."""
    delen = ruimte.aantal_kamers_toegang or aantal_kamers
    per_m2 = 1.0 if ruimte.is_vertrek else 0.75
    opp = (per_m2 * ruimte.oppervlakte_m2) / ruimte.aantal_adressen / delen
    verw = 0.0
    if ruimte.verwarmd:
        verw_totaal = 2.0 if ruimte.is_vertrek else 1.0
        verw = verw_totaal / ruimte.aantal_adressen / delen
    return opp, verw


def _gem_buitenruimte_punten_per_kamer(bui: GemeenschappelijkeBuitenruimte, aantal_kamers: int) -> float:
    delen = bui.aantal_kamers_toegang or aantal_kamers
    return (0.75 * bui.oppervlakte_m2) / bui.aantal_adressen / delen


# ---------------------------------------------------------------------------
# Volledige berekening
# ---------------------------------------------------------------------------
def bereken_woning(woning: Woning) -> list[KamerResultaat]:
    """Bereken punten + maximale kale huur voor elke kamer op het adres."""
    from .wwso_huur import max_huur_bij_punten

    aantal_kamers = len(woning.kamers)
    if aantal_kamers == 0:
        return []

    energie_ppm2 = _energie_punten_per_m2(woning)
    woz = _rond_op_kwart(_woz_punten(woning))

    # Gedeelde voorzieningen: per kamer identiek, dus één keer berekenen.
    keuken_pk = (
        _keuken_punten_per_kamer(woning.gedeelde_keuken, aantal_kamers)
        if woning.gedeelde_keuken
        else 0.0
    )
    san_gedeeld_pk = (
        _sanitair_punten_per_kamer(woning.gedeeld_sanitair, aantal_kamers)
        if woning.gedeeld_sanitair
        else 0.0
    )

    gem_opp_pk = 0.0
    gem_verw_pk = 0.0
    gem_vertrek_m2_pk = 0.0  # toegerekende gedeelde vertrek-m² (voor energie)
    for ruimte in woning.gedeelde_ruimten:
        opp, verw = _gedeelde_ruimte_punten_per_kamer(ruimte, aantal_kamers)
        gem_opp_pk += opp
        gem_verw_pk += verw
        if ruimte.is_vertrek:
            delen = ruimte.aantal_kamers_toegang or aantal_kamers
            gem_vertrek_m2_pk += ruimte.oppervlakte_m2 / ruimte.aantal_adressen / delen

    gem_bui_pk = (
        _gem_buitenruimte_punten_per_kamer(
            woning.gemeenschappelijke_buitenruimte, aantal_kamers
        )
        if woning.gemeenschappelijke_buitenruimte
        else 0.0
    )

    resultaten: list[KamerResultaat] = []
    for kamer in woning.kamers:
        rub: dict[str, float] = {}

        # Rubriek 1+2: oppervlakte (privé vertrek 1/m², privé overige 0,75/m²)
        # + toegerekende gemeenschappelijke binnenruimten (rubriek 9).
        prive_vertrek_m2 = _rond_m2(kamer.oppervlakte_m2)
        opp_punten = prive_vertrek_m2 * 1.0
        opp_punten += _rond_m2(kamer.prive_overige_m2) * 0.75 if kamer.prive_overige_m2 else 0.0
        opp_punten += gem_opp_pk
        rub["oppervlakte"] = _rond_op_kwart(opp_punten)

        # Rubriek 3: verwarming (eigen vertrek 2 punten + gedeelde verwarming)
        verw = (2.0 if kamer.verwarmd else 0.0) + gem_verw_pk
        rub["verwarming"] = _rond_op_kwart(verw)

        # Rubriek 4: energieprestatie over privé + toegerekende gedeelde vertrek-m².
        energie_m2 = kamer.oppervlakte_m2 + gem_vertrek_m2_pk
        rub["energie"] = _rond_op_kwart(energie_ppm2 * energie_m2)

        # Rubriek 5: keuken (gedeeld).
        rub["keuken"] = _rond_op_kwart(keuken_pk)

        # Rubriek 6: sanitair (gedeeld + eventueel privé).
        san = san_gedeeld_pk + _prive_sanitair_punten(kamer.prive_sanitair)
        rub["sanitair"] = _rond_op_kwart(san)

        # Rubriek 8: buitenruimte (privé + gemeenschappelijk, samen max 15).
        bui = 0.0
        if kamer.prive_buitenruimte_m2:
            bui += 2.0 + 0.35 * kamer.prive_buitenruimte_m2
        bui += gem_bui_pk
        rub["buitenruimte"] = min(_rond_op_kwart(bui), 15.0)

        # Rubriek 11: WOZ.
        rub["woz"] = woz

        totaal_ruw = sum(rub.values())
        totaal = _rond_op_hele_punten(totaal_ruw)
        resultaten.append(
            KamerResultaat(
                kamer=kamer,
                punten_per_rubriek=rub,
                totaal_punten=totaal,
                max_kale_huur=max_huur_bij_punten(totaal),
            )
        )
    return resultaten
