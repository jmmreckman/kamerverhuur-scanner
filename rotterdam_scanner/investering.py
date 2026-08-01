"""Investeringsberekening voor een kansrijke woning: tweetraps-financiering
(taxatie vóór vergunning op basis van de koopsom, taxatie ná vergunning op basis
van de te verwachten huurinkomsten), waarna de lening na vergunning wordt
"opgehoogd" naar 80% van de hogere taxatie. Geverifieerd tegen een handmatig
doorgerekend praktijkvoorbeeld (koopsom €403.000, 115 m² BAG, geen opslag) --
zie tests/test_investering.py.

Alleen de twee kernuitkomsten (winst_pm_pp, eigen_inleg_na_ophoging_pp) worden
elders gebruikt (pipeline.py/report.py); de tussenstappen staan in
InvesteringsResultaat voor het geval ze ooit nodig zijn (bv. debuggen).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# UITGANGSPUNTEN - hier aanpassen als de aannames wijzigen.
OVERDRACHTSBELASTING = 0.08
BAR = 0.076
KALE_HUUR_PER_KAMER = 550.0
SERVICEKOSTEN_PER_KAMER = 210.0
VASTE_KOSTEN_PER_HUURDER = 100.0
KOSTEN_KOPER_EX_OVB = 6_000.0
VERBOUWKOSTEN = 25_000.0
RENTE = 0.058
TAXATIE_VERHOUDING_VOOR_VERHOGING = 0.875
LTV = 0.8
AANTAL_INVESTEERDERS = 2
M2_PER_STUDENTENKAMER = 18
# Als het handmatig ingevoerde aantal kamers lager is dan wat de 18m2-vuistregel op
# basis van de oppervlakte zou geven (bv. omdat de plattegrond/raamindeling minder
# kamers toelaat dan de m2 doet vermoeden), telt dit percentage van de kale huur die de
# "verloren" kamers zouden hebben opgeleverd alsnog mee, verdeeld over de overgebleven
# kamers - die zijn dan immers navenant ruimer (en dus meer waard) dan een standaard
# 18m2-studentenkamer, dus puur op het aantal kamers rekenen onderschat de huurwaarde.
KAMERVERLIES_COMPENSATIE = 0.5


@dataclass(frozen=True)
class InvesteringsResultaat:
    aantal_kamers: int
    taxatie_voor_vergunning: float
    taxatie_na_vergunning: float
    leenbaar_voor_verhoging: float
    leenbaar_na_verhoging: float
    verhoogbaar_met: float
    totale_zelf_in_te_leggen: float
    winst_pm_pp: float
    eigen_inleg_na_ophoging_pp: float


def aantal_kamers_mogelijk(m2: float) -> int:
    """Losstaand herbruikbaar (o.a. voor de rapporttabel) zodat het aantal kamers ook
    getoond kan worden wanneer de volledige investeringsberekening niet kan draaien
    (bv. vraagprijs nog onbekend). `m2` is de leidende oppervlakte (advertentie-m2 als
    die bekend is, anders BAG-m2 als fallback - zie ListingState.primaire_oppervlakte)."""
    return math.floor(m2 / M2_PER_STUDENTENKAMER)


def bereken(m2: float, koopsom: float, opslag_percentage: float = 0.0) -> InvesteringsResultaat | None:
    """`m2` is de leidende oppervlakte (advertentie-m2 als die bekend is, anders BAG-m2
    als fallback - zie ListingState.primaire_oppervlakte). `opslag_percentage` is de
    hoogste toepasselijke WWS-huurprijsopslag (bv. 0.05 voor 5% beschermd stadsgezicht,
    zie monumenten.hoogste_opslagpercentage) en werkt door in zowel de kale huur als
    (via de taxatie na vergunning) de lening en rente.

    Geeft None terug als er geen enkele studentenkamer mogelijk is (te kleine
    oppervlakte) - dan is dit sowieso geen bruikbare kans."""
    return bereken_met_aantal_kamers(aantal_kamers_mogelijk(m2), koopsom, opslag_percentage, m2=m2)


def bereken_met_aantal_kamers(
    aantal_kamers: int, koopsom: float, opslag_percentage: float = 0.0, m2: float | None = None
) -> InvesteringsResultaat | None:
    """Zelfde berekening als `bereken()`, maar met een al vaststaand aantal kamers i.p.v.
    dat af te leiden uit de oppervlakte - voor de handmatige "aantal kamers"-correctie op
    de kaart-website (de 18m2-vuistregel klopt in de praktijk niet altijd, bv. bij een
    ongunstige plattegrond).

    Geef ook `m2` mee als die bekend is: als `aantal_kamers` lager uitvalt dan wat de
    18m2-vuistregel op basis van die m2 zou geven, wordt de kale huur verhoogd met
    KAMERVERLIES_COMPENSATIE van de huurwaarde van de "verloren" kamers (zie hierboven) -
    zonder `m2` wordt die correctie niet toegepast (bv. bij `bereken_met_aantal_kamers()`
    zonder bekende oppervlakte)."""
    if aantal_kamers < 1:
        return None

    kale_huur_pm = aantal_kamers * KALE_HUUR_PER_KAMER * (1 + opslag_percentage)
    if m2 is not None:
        kamers_verloren = max(0, aantal_kamers_mogelijk(m2) - aantal_kamers)
        kale_huur_pm += (
            kamers_verloren * KALE_HUUR_PER_KAMER * (1 + opslag_percentage) * KAMERVERLIES_COMPENSATIE
        )

    service_in_pm = aantal_kamers * SERVICEKOSTEN_PER_KAMER
    vast_uit_pm = aantal_kamers * VASTE_KOSTEN_PER_HUURDER

    taxatie_voor_vergunning = koopsom * TAXATIE_VERHOUDING_VOOR_VERHOGING
    taxatie_na_vergunning = (kale_huur_pm * 12) / BAR

    leenbaar_voor_verhoging = LTV * taxatie_voor_vergunning
    leenbaar_na_verhoging = LTV * taxatie_na_vergunning
    verhoogbaar_met = leenbaar_na_verhoging - leenbaar_voor_verhoging

    overdrachtsbelasting = koopsom * OVERDRACHTSBELASTING
    zelf_in_te_leggen_bij_aankoop = koopsom - leenbaar_voor_verhoging

    rente_pm_na_verhoging = leenbaar_na_verhoging * RENTE / 12
    leegstand_3mnd = 3 * rente_pm_na_verhoging

    totale_zelf_in_te_leggen = (
        zelf_in_te_leggen_bij_aankoop
        + overdrachtsbelasting
        + KOSTEN_KOPER_EX_OVB
        + VERBOUWKOSTEN
        + leegstand_3mnd
    )

    eigen_inleg_na_ophoging_pp = (totale_zelf_in_te_leggen - verhoogbaar_met) / AANTAL_INVESTEERDERS
    winst_pm_pp = (kale_huur_pm + service_in_pm - vast_uit_pm - rente_pm_na_verhoging) / AANTAL_INVESTEERDERS

    return InvesteringsResultaat(
        aantal_kamers=aantal_kamers,
        taxatie_voor_vergunning=taxatie_voor_vergunning,
        taxatie_na_vergunning=taxatie_na_vergunning,
        leenbaar_voor_verhoging=leenbaar_voor_verhoging,
        leenbaar_na_verhoging=leenbaar_na_verhoging,
        verhoogbaar_met=verhoogbaar_met,
        totale_zelf_in_te_leggen=totale_zelf_in_te_leggen,
        winst_pm_pp=winst_pm_pp,
        eigen_inleg_na_ophoging_pp=eigen_inleg_na_ophoging_pp,
    )


# --- Interactieve rekentool (kansen.steenhub.nl) -------------------------------
# Zelfde tweetraps-financieringsmodel als hierboven, maar met álle uitgangspunten
# als losse (per woning aanpasbare) parameters i.p.v. de module-constanten, en met
# een volledig resultaat (alle tussenstappen) zodat de rekenpagina links de invoer
# en rechts de doorgerekende sommen kan tonen. Geverifieerd tegen een handmatig
# doorgerekend praktijkvoorbeeld (Azaleastraat 82B, koopsom €355.000, 6 kamers) -
# zie tests/test_rekentool.py. Bewust géén kamerverlies-compensatie of
# huurprijsopslag hier: op de handmatige rekenpagina vult de gebruiker elke
# uitgangspunt zelf in, dus die verborgen correcties zouden alleen maar verwarren.


@dataclass(frozen=True)
class RekenUitgangspunten:
    koopsom: float
    aantal_kamers: int
    aantal_investeerders: int = AANTAL_INVESTEERDERS
    overdrachtsbelasting: float = OVERDRACHTSBELASTING
    bar: float = BAR
    kale_huur_per_kamer: float = KALE_HUUR_PER_KAMER
    servicekosten_per_kamer: float = SERVICEKOSTEN_PER_KAMER
    vaste_kosten_per_huurder: float = VASTE_KOSTEN_PER_HUURDER
    kosten_koper_ex_ovb: float = KOSTEN_KOPER_EX_OVB
    verbouwkosten: float = VERBOUWKOSTEN
    rente: float = RENTE
    taxatie_verhouding_voor_verhoging: float = TAXATIE_VERHOUDING_VOOR_VERHOGING
    ltv: float = LTV


@dataclass(frozen=True)
class RekenResultaat:
    # Berekende uitgangspunten (tussenstappen)
    kale_huur_pm: float
    service_in_pm: float
    vast_uit_pm: float
    overdrachtsbelasting_eur: float
    taxatie_voor_vergunning: float
    taxatie_na_vergunning: float
    leenbaar_voor_verhoging: float
    leenbaar_na_verhoging: float
    zelf_in_te_leggen_bij_aankoop: float
    rente_pm_na_verhoging: float
    leegstand_3mnd: float
    totale_zelf_in_te_leggen: float
    verhoogbaar_met: float
    # Belangrijke resultaten
    winst_pm_pp: float
    eigen_inleg_voor_ophoging_totaal: float
    eigen_inleg_na_ophoging_pp: float
    rendement: float | None  # winst/jaar p.p. gedeeld door eigen inleg na ophoging; None bij inleg 0


def bereken_rekentool(u: RekenUitgangspunten) -> RekenResultaat:
    kale_huur_pm = u.aantal_kamers * u.kale_huur_per_kamer
    service_in_pm = u.aantal_kamers * u.servicekosten_per_kamer
    vast_uit_pm = u.aantal_kamers * u.vaste_kosten_per_huurder

    overdrachtsbelasting_eur = u.koopsom * u.overdrachtsbelasting
    taxatie_voor_vergunning = u.koopsom * u.taxatie_verhouding_voor_verhoging
    taxatie_na_vergunning = (kale_huur_pm * 12) / u.bar if u.bar else 0.0

    leenbaar_voor_verhoging = u.ltv * taxatie_voor_vergunning
    leenbaar_na_verhoging = u.ltv * taxatie_na_vergunning
    verhoogbaar_met = leenbaar_na_verhoging - leenbaar_voor_verhoging

    zelf_in_te_leggen_bij_aankoop = u.koopsom - leenbaar_voor_verhoging
    rente_pm_na_verhoging = leenbaar_na_verhoging * u.rente / 12
    leegstand_3mnd = 3 * rente_pm_na_verhoging

    totale_zelf_in_te_leggen = (
        zelf_in_te_leggen_bij_aankoop
        + overdrachtsbelasting_eur
        + u.kosten_koper_ex_ovb
        + u.verbouwkosten
        + leegstand_3mnd
    )

    n = u.aantal_investeerders or 1
    winst_pm_pp = (kale_huur_pm + service_in_pm - vast_uit_pm - rente_pm_na_verhoging) / n
    eigen_inleg_na_ophoging_pp = (totale_zelf_in_te_leggen - verhoogbaar_met) / n
    rendement = (winst_pm_pp * 12 / eigen_inleg_na_ophoging_pp) if eigen_inleg_na_ophoging_pp else None

    return RekenResultaat(
        kale_huur_pm=kale_huur_pm,
        service_in_pm=service_in_pm,
        vast_uit_pm=vast_uit_pm,
        overdrachtsbelasting_eur=overdrachtsbelasting_eur,
        taxatie_voor_vergunning=taxatie_voor_vergunning,
        taxatie_na_vergunning=taxatie_na_vergunning,
        leenbaar_voor_verhoging=leenbaar_voor_verhoging,
        leenbaar_na_verhoging=leenbaar_na_verhoging,
        zelf_in_te_leggen_bij_aankoop=zelf_in_te_leggen_bij_aankoop,
        rente_pm_na_verhoging=rente_pm_na_verhoging,
        leegstand_3mnd=leegstand_3mnd,
        totale_zelf_in_te_leggen=totale_zelf_in_te_leggen,
        verhoogbaar_met=verhoogbaar_met,
        winst_pm_pp=winst_pm_pp,
        eigen_inleg_voor_ophoging_totaal=totale_zelf_in_te_leggen,
        eigen_inleg_na_ophoging_pp=eigen_inleg_na_ophoging_pp,
        rendement=rendement,
    )
