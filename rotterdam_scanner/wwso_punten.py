"""Puntentelling voor onzelfstandige woonruimte (WWSO), volgens het
"Beleidsboek waardering onzelfstandige woonruimte" (versie juli 2026) van de
Huurcommissie.

De berekening gaat uit van één woonadres met meerdere onzelfstandige
woonruimten (kamers). Elke kamer is opgebouwd uit zijn eigen (privé)ruimtes en
voorzieningen; daarnaast is er een lijst gedeelde ruimtes die per rubriek wordt
gedeeld over het aantal kamers dat er toegang en gebruiksrecht toe heeft.

De uitkomst per kamer is een puntentotaal; via wwso_huur.max_huur_bij_punten
volgt daaruit de maximale kale huurprijs. Deze module berekent alleen de punten.

Belangrijkste rekenregels (hoofdstuk 2 van het beleidsboek):
 - Rubriek 1 (vertrekken): 1 punt per m².
 - Rubriek 2 (overige ruimten): 0,75 punt per m².
 - Rubriek 3 (verwarming): 2 punten per verwarmd vertrek; 1 punt per verwarmde
   overige/verkeersruimte (die twee samen max 4). Een verwarmde kamer met open
   keuken telt als twee verwarmde vertrekken (2.3.2): 2 + 2 = 4 punten.
 - Rubriek 4 (energieprestatie): punten/m² x (privé + toegerekende gedeelde
   vertrek-m²), afhankelijk van energielabel of bouwjaar.
 - Rubriek 5 (keuken): basispunten op aanrechtlengte + extra voorzieningen
   (afgetopt op de basispunten). Een eigen keuken telt volledig; een gedeelde
   keuken wordt gedeeld door het aantal kamers met toegang.
 - Rubriek 6 (sanitair): punten per voorziening; gedeeld sanitair gedeeld door
   het aantal kamers met toegang.
 - Rubriek 8 (buitenruimte): privé 2 punten + 0,35/m²; gemeenschappelijk
   0,75/m² gedeeld door adressen en kamers (samen max 15).
 - Rubriek 9 (gemeenschappelijke binnenruimten): 1/m² (vertrek) of 0,75/m²
   (overige), gedeeld door adressen en kamers.
 - Rubriek 11 (WOZ): 10/12/14 punten op basis van WOZ-waarde/m² t.o.v. het
   COROP-gemiddelde.
 - Afronding: per rubriek op 0,25 punt (vanaf 1/8 omhoog), eindtotaal op hele
   punten (vanaf 0,5 omhoog). Boven 250 punten: zie wwso_huur.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# --- Energielabel -> punten per m² (rubriek 4, NTA 8800 vanaf 1-1-2021) --------
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
    (2002, 0.65),
    (2000, 0.50),
    (1992, 0.35),
    (1984, 0.20),
    (1979, -0.05),
    (1977, -0.10),
    (0, -0.15),
]

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

# Sanitaire (basis)voorzieningen (rubriek 6) -> punten.
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

# Soorten gedeelde ruimtes (rubriek 9 e.a.).
_VERTREK, _OVERIGE, _VERKEER = "vertrek", "overige", "verkeer"
_KEUKEN, _SANITAIR, _BUITEN = "keuken", "sanitair", "buitenruimte"
_MAX_OVERIGE_VERKEER_VERWARMING = 4.0  # rubriek 3
_MAX_BUITENRUIMTE = 15.0               # rubriek 8


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


def _rond_op_kwart(punten: float) -> float:
    """Afronden op 0,25 punt; vanaf 1/8 (0,125) punt naar boven (2.1.6)."""
    return round(math.floor(punten / 0.25 + 0.5 + 1e-9) * 0.25, 2)


def _rond_op_hele_punten(punten: float) -> int:
    """Eindsaldering op hele punten; vanaf 0,5 naar boven (2.1.7)."""
    return int(math.floor(punten + 0.5 + 1e-9))


def _rond_m2(m2: float) -> int:
    """Oppervlakte afronden op hele m²; 0,50 omhoog, 0,49 of lager omlaag."""
    return int(math.floor(m2 + 0.5 + 1e-9))


# ---------------------------------------------------------------------------
# Invoermodel
# ---------------------------------------------------------------------------
@dataclass
class Keuken:
    """Een keukenblok (aanrechtlengte + inbouwvoorzieningen)."""
    aanrecht_m: float
    voorzieningen: list[str] = field(default_factory=list)
    extra_kastruimte_60cm: int = 0


@dataclass
class Kamer:
    """Eén onzelfstandige woonruimte, opgebouwd uit privégegevens."""
    oppervlakte_m2: float                 # de kamer zelf (privévertrek), 1 pt/m²
    verwarmd: bool = True                 # eigen vertrek verwarmd (2 punten)
    # Eigen keukenblok in de kamer (open keuken). Telt volledig voor deze kamer
    # en - indien de kamer verwarmd is - als tweede verwarmd vertrek (+2, 2.3.2).
    keuken: Keuken | None = None
    eigen_sanitair: list[str] = field(default_factory=list)
    eigen_overige_m2: float = 0.0         # eigen berging/bijkeuken (0,75/m²)
    eigen_buitenruimte_m2: float = 0.0    # eigen balkon/tuin (2 + 0,35/m²)


@dataclass
class GedeeldeRuimte:
    """Een gedeelde ruimte of voorziening op het adres. `soort` bepaalt de
    waardering: 'vertrek' (1/m²), 'overige' (0,75/m²), 'verkeer' (0 opp., wel
    verwarming), 'keuken', 'sanitair' of 'buitenruimte'."""
    soort: str
    oppervlakte_m2: float = 0.0
    verwarmd: bool = False
    aantal_adressen: int = 1
    aantal_kamers_toegang: int | None = None  # None = alle kamers op het adres
    keuken: Keuken | None = None              # soort == 'keuken'
    sanitair: list[str] = field(default_factory=list)  # soort == 'sanitair'


@dataclass
class Woning:
    """Een woonadres met onzelfstandige woonruimten (kamers)."""
    kamers: list[Kamer]
    energielabel: str | None = None
    bouwjaar: int | None = None
    woz_waarde: float | None = None
    woz_oppervlakte_m2: float | None = None
    corop_gemiddelde_woz_m2: float | None = None
    gedeelde_ruimten: list[GedeeldeRuimte] = field(default_factory=list)


@dataclass
class KamerResultaat:
    kamer: Kamer
    punten_per_rubriek: dict[str, float]
    totaal_punten: int
    max_kale_huur: float


# ---------------------------------------------------------------------------
# Rubriek-hulpjes
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
    return -0.15


def _woz_punten(woning: Woning) -> float:
    if not (woning.woz_waarde and woning.woz_oppervlakte_m2 and woning.corop_gemiddelde_woz_m2):
        return 10.0
    woz_per_m2 = woning.woz_waarde / woning.woz_oppervlakte_m2
    verhouding = woz_per_m2 / woning.corop_gemiddelde_woz_m2
    if verhouding > 1.10:
        return 14.0
    if verhouding < 0.90:
        return 10.0
    return 12.0


def _keuken_punten(keuken: Keuken, delen: int) -> float:
    """Ruwe keukenpunten (basis + afgetopte extra's), gedeeld door `delen`
    kamers met toegang."""
    delen = max(1, delen)
    basis = _keuken_basispunten(keuken.aanrecht_m, delen)
    if basis == 0:
        return 0.0  # zonder basisvoorzieningen geen keukenpunten (ook geen extra)
    extra = sum(KEUKEN_VOORZIENINGEN[v] for v in keuken.voorzieningen if v in KEUKEN_VOORZIENINGEN)
    extra += keuken.extra_kastruimte_60cm * 0.75
    extra = min(extra, basis)  # extra afgetopt op de basispunten
    return (basis + extra) / delen


def _sanitair_punten(voorzieningen: list[str]) -> float:
    return sum(SANITAIR_VOORZIENINGEN[v] for v in voorzieningen if v in SANITAIR_VOORZIENINGEN)


# ---------------------------------------------------------------------------
# Volledige berekening
# ---------------------------------------------------------------------------
def _gedeelde_bijdragen(woning: Woning, aantal_kamers: int) -> dict[str, float]:
    """Per-kamer-aandeel van alle gedeelde ruimtes (identiek voor elke kamer die
    toegang heeft). Geeft ruwe (nog niet afgeronde) punten per rubriek + de
    toegerekende gedeelde vertrek-m² voor de energierubriek."""
    b = {
        "oppervlakte": 0.0, "vertrek_verwarming": 0.0, "overige_verkeer_verwarming": 0.0,
        "keuken": 0.0, "sanitair": 0.0, "buitenruimte": 0.0, "vertrek_m2": 0.0,
    }
    for r in woning.gedeelde_ruimten:
        delen = r.aantal_kamers_toegang or aantal_kamers
        delers = max(1, r.aantal_adressen) * max(1, delen)
        if r.soort == _VERTREK:
            b["oppervlakte"] += (1.0 * r.oppervlakte_m2) / delers
            b["vertrek_m2"] += r.oppervlakte_m2 / delers
            if r.verwarmd:
                b["vertrek_verwarming"] += 2.0 / delers
        elif r.soort == _OVERIGE:
            b["oppervlakte"] += (0.75 * r.oppervlakte_m2) / delers
            if r.verwarmd:
                b["overige_verkeer_verwarming"] += 1.0 / delers
        elif r.soort == _VERKEER:
            # Verkeersruimte krijgt geen oppervlaktepunten, wel verwarming.
            if r.verwarmd:
                b["overige_verkeer_verwarming"] += 1.0 / delers
        elif r.soort == _KEUKEN and r.keuken:
            b["keuken"] += _keuken_punten(r.keuken, delen)
        elif r.soort == _SANITAIR:
            b["sanitair"] += _sanitair_punten(r.sanitair) / max(1, delen)
        elif r.soort == _BUITEN:
            b["buitenruimte"] += (0.75 * r.oppervlakte_m2) / delers
    return b


def bereken_woning(woning: Woning) -> list[KamerResultaat]:
    """Bereken punten + maximale kale huur voor elke kamer op het adres."""
    from .wwso_huur import max_huur_bij_punten

    aantal_kamers = len(woning.kamers)
    if aantal_kamers == 0:
        return []

    energie_ppm2 = _energie_punten_per_m2(woning)
    woz = _rond_op_kwart(_woz_punten(woning))
    gedeeld = _gedeelde_bijdragen(woning, aantal_kamers)

    resultaten: list[KamerResultaat] = []
    for kamer in woning.kamers:
        rub: dict[str, float] = {}

        # Rubriek 1+2: oppervlakte (privévertrek 1/m² + eigen overige 0,75/m²
        # + toegerekende gedeelde binnenruimten).
        opp = _rond_m2(kamer.oppervlakte_m2) * 1.0
        if kamer.eigen_overige_m2:
            opp += _rond_m2(kamer.eigen_overige_m2) * 0.75
        opp += gedeeld["oppervlakte"]
        rub["oppervlakte"] = _rond_op_kwart(opp)

        # Rubriek 3: verwarming. Vertrekken (kamer + eventuele verwarmde open
        # keuken + gedeelde vertrekken) tellen 2 elk, zonder maximum; overige/
        # verkeersruimten samen max 4.
        vertrek_verw = (2.0 if kamer.verwarmd else 0.0) + gedeeld["vertrek_verwarming"]
        if kamer.keuken and kamer.verwarmd:
            vertrek_verw += 2.0  # open keuken als tweede verwarmd vertrek (2.3.2)
        overige_verw = min(gedeeld["overige_verkeer_verwarming"], _MAX_OVERIGE_VERKEER_VERWARMING)
        rub["verwarming"] = _rond_op_kwart(vertrek_verw + overige_verw)

        # Rubriek 4: energieprestatie over privé + toegerekende gedeelde vertrek-m².
        energie_m2 = kamer.oppervlakte_m2 + gedeeld["vertrek_m2"]
        rub["energie"] = _rond_op_kwart(energie_ppm2 * energie_m2)

        # Rubriek 5: keuken (eigen keuken volledig + aandeel gedeelde keuken(s)).
        keuken = gedeeld["keuken"]
        if kamer.keuken:
            keuken += _keuken_punten(kamer.keuken, 1)
        rub["keuken"] = _rond_op_kwart(keuken)

        # Rubriek 6: sanitair (eigen + aandeel gedeeld).
        san = _sanitair_punten(kamer.eigen_sanitair) + gedeeld["sanitair"]
        rub["sanitair"] = _rond_op_kwart(san)

        # Rubriek 8: buitenruimte (privé + gedeeld, samen max 15).
        bui = 0.0
        if kamer.eigen_buitenruimte_m2:
            bui += 2.0 + 0.35 * kamer.eigen_buitenruimte_m2
        bui += gedeeld["buitenruimte"]
        rub["buitenruimte"] = min(_rond_op_kwart(bui), _MAX_BUITENRUIMTE)

        # Rubriek 11: WOZ.
        rub["woz"] = woz

        totaal = _rond_op_hele_punten(sum(rub.values()))
        resultaten.append(
            KamerResultaat(
                kamer=kamer,
                punten_per_rubriek=rub,
                totaal_punten=totaal,
                max_kale_huur=max_huur_bij_punten(totaal),
            )
        )
    return resultaten
