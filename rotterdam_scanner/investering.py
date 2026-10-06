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
# Rente-dragende periodes vóór er huur binnenkomt (vast, niet instelbaar in de
# rekentool). Tijdens de verbouwing betaal je rente over de volle lening; daarna
# nog een paar maanden leegstand tot de kamers verhuurd zijn. Zo berekent ook de
# financieringsopzet van de hypotheekadviseur de "aan te tonen eigen middelen".
VERBOUWING_RENTE_MAANDEN = 6
LEEGSTAND_RENTE_MAANDEN = 3
M2_PER_STUDENTENKAMER = 18
# Als het handmatig ingevoerde aantal kamers lager is dan wat de 18m2-vuistregel op
# basis van de oppervlakte zou geven (bv. omdat de plattegrond/raamindeling minder
# kamers toelaat dan de m2 doet vermoeden), telt dit percentage van de kale huur die de
# "verloren" kamers zouden hebben opgeleverd alsnog mee, verdeeld over de overgebleven
# kamers - die zijn dan immers navenant ruimer (en dus meer waard) dan een standaard
# 18m2-studentenkamer, dus puur op het aantal kamers rekenen onderschat de huurwaarde.
KAMERVERLIES_COMPENSATIE = 0.5
# Interest Coverage Ratio (huur / rente). Boven deze norm vindt de geldverstrekker
# de rentelasten comfortabel gedekt door de huur; eronder wordt het krap.
ICR_NORM = 1.25
# Vóór de kamerverhuurvergunning staat het pand nog als gewone woning te huur. We
# schatten die woninghuur op een vaste, veilige standaard per vierkante meter maal de
# oppervlakte uit de advertentie (niet de BAG-oppervlakte) - zo is de ICR vóór ophoging
# onderbouwd op de werkelijke m² i.p.v. een ruwe fractie van de kamerhuur.
HUUR_PER_M2_VOOR_OPHOGING = 17.60


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
    # Woonoppervlak (m²) uit de advertentie, gebruikt voor de ICR vóór ophoging
    # (woninghuur = HUUR_PER_M2_VOOR_OPHOGING × oppervlakte). 0 = onbekend → ICR vóór
    # wordt dan niet berekend. Geen door de gebruiker bewerkbaar rekenveld; komt uit de
    # woning zelf (zie kansen_site/app.py: _huidige_uitgangspunten).
    oppervlakte_m2: float = 0.0


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
    # Financieringsopzet-stijl (zoals de hypotheekadviseur rekent) - leidt naar het
    # bedrag aan eigen middelen dat je moet kunnen aantonen:
    financieringslasten_verbouwing: float      # rente over de volle lening tijdens de verbouwing
    in_te_brengen_bij_passeren: float          # koopsom + OVB + k.k. - wat bij de notaris wordt uitgekeerd
    opname_liquiditeit_na_verbouwing: float    # bouwdepot - verbouwkosten (komt na verbouwing als cash terug)
    aan_te_tonen_middelen: float               # totaal aan eigen middelen dat je moet aantonen
    # Interest Coverage Ratio (huur / rente); None als er geen rente is (lening 0)
    icr_voor_ophoging: float | None            # woninghuur (€/m² × advertentie-m²) / rente op lening vóór verhoging
    icr_na_ophoging: float | None              # volledige kamerhuur / rente op lening ná verhoging
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
    leegstand_3mnd = LEEGSTAND_RENTE_MAANDEN * rente_pm_na_verhoging

    totale_zelf_in_te_leggen = (
        zelf_in_te_leggen_bij_aankoop
        + overdrachtsbelasting_eur
        + u.kosten_koper_ex_ovb
        + u.verbouwkosten
        + leegstand_3mnd
    )

    # --- Financieringsopzet-stijl: "aan te tonen eigen middelen" --------------
    # Zo rekent de hypotheekadviseur (zie financieringsopzet Menkemaborgstraat):
    #  - Bij de notaris wordt leenbaar_voor_verhoging uitgekeerd; jij legt het
    #    verschil met koopsom + overdrachtsbelasting + kosten koper zelf in.
    #  - De verbouwing wordt uit het bouwdepot betaald (dus NIET uit eigen geld),
    #    maar tijdens de verbouwing betaal je wel rente over de volle lening, en
    #    daarna nog de eerste maanden leegstand - die rente moet je zelf meebrengen.
    #  - Overdrachtsbelasting en rente zitten hier via de losse invoervelden in,
    #    dus een lager OVB-tarief of een andere rente werkt automatisch door.
    # De verbouwkosten zelf tellen hier bewust NIET mee (bouwdepot), in
    # tegenstelling tot 'totale_zelf_in_te_leggen' hierboven.
    financieringslasten_verbouwing = VERBOUWING_RENTE_MAANDEN * rente_pm_na_verhoging
    in_te_brengen_bij_passeren = (
        u.koopsom + overdrachtsbelasting_eur + u.kosten_koper_ex_ovb - leenbaar_voor_verhoging
    )
    opname_liquiditeit_na_verbouwing = verhoogbaar_met - u.verbouwkosten
    aan_te_tonen_middelen = (
        in_te_brengen_bij_passeren + financieringslasten_verbouwing + leegstand_3mnd
    )

    # --- Interest Coverage Ratio (ICR = huur / rente) -------------------------
    # Twee momenten: vóór de vergunning (woninghuur op de kleinere lening) en ná
    # ophoging (volledige kamerhuur op de volledige lening). We rekenen met de kale
    # huur, net als de geldverstrekker. Boven ICR_NORM (1,25) zijn de rentelasten
    # comfortabel gedekt. De woninghuur vóór ophoging schatten we op een vaste
    # standaard per m² (HUUR_PER_M2_VOOR_OPHOGING) maal de advertentie-oppervlakte;
    # zonder bekende oppervlakte is de ICR vóór ophoging niet te bepalen (None).
    rente_pm_voor_verhoging = leenbaar_voor_verhoging * u.rente / 12
    huur_voor_ophoging = u.oppervlakte_m2 * HUUR_PER_M2_VOOR_OPHOGING
    icr_voor_ophoging = (
        huur_voor_ophoging / rente_pm_voor_verhoging
        if (rente_pm_voor_verhoging and u.oppervlakte_m2) else None
    )
    icr_na_ophoging = (
        kale_huur_pm / rente_pm_na_verhoging if rente_pm_na_verhoging else None
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
        financieringslasten_verbouwing=financieringslasten_verbouwing,
        in_te_brengen_bij_passeren=in_te_brengen_bij_passeren,
        opname_liquiditeit_na_verbouwing=opname_liquiditeit_na_verbouwing,
        aan_te_tonen_middelen=aan_te_tonen_middelen,
        icr_voor_ophoging=icr_voor_ophoging,
        icr_na_ophoging=icr_na_ophoging,
        winst_pm_pp=winst_pm_pp,
        eigen_inleg_voor_ophoging_totaal=totale_zelf_in_te_leggen,
        eigen_inleg_na_ophoging_pp=eigen_inleg_na_ophoging_pp,
        rendement=rendement,
    )
