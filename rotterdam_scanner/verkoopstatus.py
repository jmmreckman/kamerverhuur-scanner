"""Verkoopstatus van een woning normaliseren voor het status-filter op
kansen.steenhub.nl.

Move levert per woning een `status` (bv. "BESCHIKBAAR", "ONDER_BOD", "VERKOCHT") en in
de kenmerken ook een Nederlands label ("Beschikbaar", "Onder bod", ...). We brengen die
terug tot een vaste set categorieën zodat de kaart er op kan filteren. De categorisatie
is tolerant (substring, hoofdletterongevoelig, werkt op zowel het enum als het NL-label)
en valt bij iets onbekends terug op "onbekend" i.p.v. een woning verkeerd te stoppen.

Pure functies, geen externe dependencies, dus los testbaar (sandbox-proof).
"""
from __future__ import annotations

# Categorieën (volgorde = aflopend "nog te koop"): een woning is beschikbaar, dan via
# optie/bod onderweg, dan (onder voorbehoud) verkocht, dan definitief weg.
BESCHIKBAAR = "beschikbaar"
IN_OPTIE = "in_optie"
ONDER_BOD = "onder_bod"
VERKOCHT_ONDER_VOORBEHOUD = "verkocht_onder_voorbehoud"
VERKOCHT = "verkocht"
INGETROKKEN = "ingetrokken"
ONBEKEND = "onbekend"

LABELS = {
    BESCHIKBAAR: "Beschikbaar",
    IN_OPTIE: "Onder optie",
    ONDER_BOD: "Onder bod",
    VERKOCHT_ONDER_VOORBEHOUD: "Verkocht o.v.",
    VERKOCHT: "Verkocht",
    INGETROKKEN: "Ingetrokken",
    ONBEKEND: "Onbekend",
}

# "Nog in de verkoop" (telt als een levende kans): beschikbaar + onderweg (optie/bod).
TE_KOOP_ACHTIG = {BESCHIKBAAR, IN_OPTIE, ONDER_BOD}
# Definitief van de markt (een gloednieuwe woning hiermee hoeven we niet te verwerken).
AFGEROND = {VERKOCHT, INGETROKKEN}


def categoriseer_verkoopstatus(rauw: str | None) -> str:
    """Normaliseert een Move-status (enum of NL-label) naar één categorie.

    Lege/None-invoer -> ONBEKEND. Volgorde van de checks is belangrijk: 'voorbehoud'
    vóór 'verkocht' (de string bevat beide), en 'ingetrokken' apart."""
    if not rauw:
        return ONBEKEND
    t = rauw.strip().upper()
    if not t:
        return ONBEKEND
    if "INGETROKKEN" in t or "VERVALLEN" in t or "INTREK" in t or "GEANNULEERD" in t:
        return INGETROKKEN
    if "VOORBEHOUD" in t:
        return VERKOCHT_ONDER_VOORBEHOUD
    if "VERKOCHT" in t:
        return VERKOCHT
    if "OPTIE" in t:
        return IN_OPTIE
    if "BOD" in t:
        return ONDER_BOD
    if "BESCHIKBAAR" in t or "TE_KOOP" in t or "TE KOOP" in t or "ACTIEF" in t:
        return BESCHIKBAAR
    return ONBEKEND


def label_voor(categorie: str | None) -> str:
    """Leesbaar NL-label voor een categorie (voor het kaart-popup)."""
    return LABELS.get(categorie or ONBEKEND, LABELS[ONBEKEND])


def is_beschikbaar(categorie: str | None) -> bool:
    return categorie == BESCHIKBAAR
