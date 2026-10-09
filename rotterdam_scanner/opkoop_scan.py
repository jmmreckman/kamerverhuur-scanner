"""Concurrentie-scan rond een adres: hoeveel woningen binnen 50 m zouden - volgens de
regels - theoretisch nog in aanmerking komen voor een kamerverhuurvergunning (4+).

Een trechter die buuradressen stap voor stap uitsluit:

1. Alle adressen binnen een straal van 50 m (PDOK reverse, gepagineerd).
2. Opkoopbescherming: zit het centrum in een beschermde wijk? Zo ja, dan vallen de
   adressen met een WOZ-waarde op/onder de grens af (zelfbewoningsplicht - lastig als
   belegging op te pakken). Zo nee, dan valt hierop niets af.
3. 50 m-norm: adressen binnen 50 m van een al verleende kamerverhuurvergunning vallen af
   (officiele Rotterdamse kaartlaag, die de 50 m-zones al bevat).
4. Overgebleven = de reële concurrentiepool. Daarop nog twee VERMELDINGEN (géén harde
   uitsluiting): de BAG-oppervlakte (< ~72 m² = krap voor 4 bewoners à 18 m², maar na
   een dakkapel kan het alsnog), en of de woning de afgelopen 12 maanden te koop stond
   (voor zover bekend in ons eigen listings-archief).

Wat NIET kan: lopende, nog niet verwerkte vergunningaanvragen opsporen. Rotterdam
publiceert kamerverhuur-aanvragen niet (alleen de uiteindelijke beslissing), dus de
~14 weken tussen aanvraag en besluit is een blinde vlek die geen publieke bron dicht.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import bag, gis, opkoop, woz
from . import geocode

# Minimale gebruiksoppervlakte voor 4 bewoners: 4 × 18 m² (norm 18 m²/persoon).
# Alleen ter vermelding - niet om hard uit te sluiten (na een dakkapel/aanbouw kan een
# krap pand alsnog aan de maat komen).
GRENS_M2_4KAMERS = 72


def _veilige_woz(nummeraanduiding_id: str) -> int | None:
    """Meest recente WOZ-waarde, of None bij geen waarde/storing (nooit een exception
    naar buiten - één hapering mag de hele scan niet laten klappen)."""
    try:
        w = woz.meest_recente_woz_waarde(nummeraanduiding_id)
        return w.bedrag if w else None
    except Exception:
        return None


def _veilige_bag_oppervlakte(adresseerbaarobject_id: str) -> int | None:
    try:
        g = bag.fetch_bag_gegevens(adresseerbaarobject_id)
        return g.oppervlakte if g else None
    except Exception:
        return None


def _veilig_binnen_50m(rd_x: float | None, rd_y: float | None) -> bool | None:
    """True/False, of None als het niet te bepalen was (geen coördinaat of ArcGIS-
    storing). None telt niet als 'valt af' - we sluiten nooit uit op onzekerheid."""
    if rd_x is None or rd_y is None:
        return None
    try:
        return gis.binnen_50m_van_kamerverhuurvergunning(rd_x, rd_y)
    except Exception:
        return None


@dataclass
class AdresRij:
    weergavenaam: str
    afstand_m: float
    nummeraanduiding_id: str
    adresseerbaarobject_id: str
    rd_x: float | None
    rd_y: float | None
    woz: int | None = None
    bag_m2: int | None = None
    binnen_50m: bool | None = None
    te_koop_laatst: str | None = None       # ISO-datum, als binnen 12 mnd te koop gezien
    reden_afgevallen: str | None = None      # None = nog in de pool


@dataclass
class ScanResultaat:
    centrum_adres: str
    straal_m: float
    grens: int                 # WOZ-grens opkoopbescherming
    m2_grens: int
    buurtnaam: str
    in_opkoopwijk: bool
    rijen: list[AdresRij] = field(default_factory=list)
    woz_onbereikbaar: bool = False
    gis_onbereikbaar: bool = False
    archief_doorzocht: bool = False

    # --- trechter-stappen ---
    @property
    def afgevallen_opkoop(self) -> list[AdresRij]:
        return [r for r in self.rijen if r.reden_afgevallen and "opkoop" in r.reden_afgevallen]

    @property
    def afgevallen_50m(self) -> list[AdresRij]:
        return [r for r in self.rijen if r.reden_afgevallen and "50 m" in r.reden_afgevallen]

    @property
    def pool(self) -> list[AdresRij]:
        """De overgebleven adressen: niet uitgesloten door opkoop of de 50 m-norm."""
        return [r for r in self.rijen if r.reden_afgevallen is None]

    # --- vermeldingen op de pool (sluiten niet uit) ---
    @property
    def pool_te_klein(self) -> list[AdresRij]:
        return [r for r in self.pool if r.bag_m2 is not None and r.bag_m2 < self.m2_grens]

    @property
    def pool_te_koop_geweest(self) -> list[AdresRij]:
        return [r for r in self.pool if r.te_koop_laatst]


def scan(lat: float, lon: float, grens: int, centrum_adres: str, *,
         straal_m: float = 50.0, m2_grens: int = GRENS_M2_4KAMERS, pauze_s: float = 0.1,
         adres_func=None, woz_func=_veilige_woz, bag_func=_veilige_bag_oppervlakte,
         vergunning_func=_veilig_binnen_50m, beschermde_wijk_func=None,
         te_koop_func=None, vandaag: date | None = None) -> ScanResultaat:
    """Voert de trechter uit. Alle externe afhankelijkheden zijn injecteerbaar zodat de
    logica los te testen is zonder echte PDOK/WOZ/BAG/ArcGIS-calls.

    `te_koop_func(weergavenaam, grens_datum_iso) -> str | None` geeft de laatste
    te-koop-datum terug als het adres sinds grens_datum te koop stond, anders None.
    None (de default) betekent: #5 overslaan (archief nog niet beschikbaar)."""
    adres_func = adres_func or geocode.adressen_binnen_straal
    beschermde_wijk_func = beschermde_wijk_func or opkoop.is_beschermde_wijk
    vandaag = vandaag or date.today()

    nabij = adres_func(lat, lon, straal_m)
    rijen = [
        AdresRij(
            weergavenaam=a.weergavenaam, afstand_m=a.afstand_m,
            nummeraanduiding_id=a.nummeraanduiding_id,
            adresseerbaarobject_id=getattr(a, "adresseerbaarobject_id", "") or "",
            rd_x=getattr(a, "rd_x", None), rd_y=getattr(a, "rd_y", None),
        )
        for a in nabij
    ]
    buurtnaam = getattr(nabij[0], "buurtnaam", "") if nabij else ""
    in_opkoopwijk = beschermde_wijk_func(buurtnaam)

    resultaat = ScanResultaat(
        centrum_adres=centrum_adres, straal_m=straal_m, grens=grens, m2_grens=m2_grens,
        buurtnaam=buurtnaam, in_opkoopwijk=in_opkoopwijk, rijen=rijen,
        archief_doorzocht=te_koop_func is not None,
    )

    # Stap 2 - opkoopbescherming (alleen zinvol in een beschermde wijk).
    if in_opkoopwijk:
        geen_enkele_woz = True
        for i, r in enumerate(rijen):
            if i and pauze_s:
                time.sleep(pauze_s)
            r.woz = woz_func(r.nummeraanduiding_id)
            if r.woz is not None:
                geen_enkele_woz = False
                if r.woz <= grens:
                    r.reden_afgevallen = "opkoopbescherming (WOZ ≤ grens)"
        if geen_enkele_woz and rijen:
            resultaat.woz_onbereikbaar = True

    # Stap 3 - 50 m-norm, op de overlevers van stap 2.
    overlevers = [r for r in rijen if r.reden_afgevallen is None]
    gis_fouten = 0
    for i, r in enumerate(overlevers):
        if i and pauze_s:
            time.sleep(pauze_s)
        r.binnen_50m = vergunning_func(r.rd_x, r.rd_y)
        if r.binnen_50m is True:
            r.reden_afgevallen = "binnen 50 m van bestaande vergunning"
        elif r.binnen_50m is None:
            gis_fouten += 1
    if overlevers and gis_fouten == len(overlevers):
        resultaat.gis_onbereikbaar = True

    # Stap 4 - vermeldingen op de pool (geen uitsluiting): BAG-m² + te-koop-geweest.
    grens_datum = (vandaag - timedelta(days=365)).isoformat()
    for i, r in enumerate(resultaat.pool):
        if i and pauze_s:
            time.sleep(pauze_s)
        r.bag_m2 = bag_func(r.adresseerbaarobject_id)
        if te_koop_func is not None:
            r.te_koop_laatst = te_koop_func(r.weergavenaam, grens_datum)

    return resultaat


def _eur(bedrag: int | None) -> str:
    if bedrag is None:
        return "onbekend"
    return "€" + format(bedrag, ",d").replace(",", ".")


def _m2(waarde: int | None) -> str:
    return f"{waarde} m²" if waarde is not None else "onbekend"


def bouw_mail(r: ScanResultaat) -> tuple[str, str, str]:
    """Geeft (onderwerp, html_body, text_body) voor de trechter-resultaatmail."""
    pool = r.pool
    onderwerp = (
        f"Concurrentie-scan {r.centrum_adres}: "
        f"{len(pool)} mogelijke adressen binnen {r.straal_m:.0f} m"
    )

    waarschuwingen = []
    if r.woz_onbereikbaar:
        waarschuwingen.append(
            "De WOZ-dienst gaf geen enkele waarde terug (tijdelijk onbereikbaar). "
            "De opkoopbescherming-stap kon daardoor niet betrouwbaar draaien."
        )
    if r.gis_onbereikbaar:
        waarschuwingen.append(
            "De Rotterdamse vergunningenkaart (ArcGIS) was niet bereikbaar. "
            "De 50 m-norm-stap kon daardoor niet draaien."
        )

    opkoop_regel = (
        f"In opkoopbescherming-wijk '{r.buurtnaam}': {len(r.afgevallen_opkoop)} adres(sen) "
        f"vallen af (WOZ ≤ {_eur(r.grens)})."
        if r.in_opkoopwijk else
        f"Niet in een opkoopbescherming-wijk ('{r.buurtnaam}') - hierop valt niets af."
    )

    # ---------- tekstversie ----------
    def _lijst_txt(titel, rijen, met_woz=False, met_m2=False, met_tekoop=False):
        regels = [f"{titel} ({len(rijen)}):"]
        for a in sorted(rijen, key=lambda x: x.afstand_m):
            extra = []
            if met_woz:
                extra.append(f"WOZ {_eur(a.woz)}")
            if met_m2:
                extra.append(f"BAG {_m2(a.bag_m2)}")
            if met_tekoop and a.te_koop_laatst:
                extra.append(f"te koop gezien t/m {a.te_koop_laatst}")
            staart = (" | " + " | ".join(extra)) if extra else ""
            regels.append(f"  - {a.weergavenaam} | {a.afstand_m:.0f} m{staart}")
        return "\n".join(regels)

    text_delen = [
        f"Concurrentie-scan rond: {r.centrum_adres}",
        f"Straal: {r.straal_m:.0f} m | WOZ-grens opkoop: {_eur(r.grens)} | "
        f"m²-grens 4 kamers: {r.m2_grens} m²",
        "",
    ]
    if waarschuwingen:
        text_delen.append("LET OP:")
        text_delen.extend(f"- {w}" for w in waarschuwingen)
        text_delen.append("")
    text_delen += [
        "TRECHTER",
        f"1. Adressen binnen {r.straal_m:.0f} m: {len(r.rijen)}",
        f"2. {opkoop_regel}",
        f"3. 50 m-norm: {len(r.afgevallen_50m)} adres(sen) vallen af "
        f"(binnen 50 m van een bestaande vergunning).",
        f"=> Overgebleven pool: {len(pool)} adres(sen) waar theoretisch nog een "
        f"4+-aanvraag op zou kunnen liggen.",
        "",
        _lijst_txt("POOL (overgebleven)", pool, met_woz=r.in_opkoopwijk, met_m2=True,
                   met_tekoop=r.archief_doorzocht),
        "",
        "VERMELDINGEN op de pool (sluiten NIET uit):",
        f"- Krap voor 4 kamers (BAG < {r.m2_grens} m²): {len(r.pool_te_klein)} "
        "(let op: na een dakkapel/aanbouw kan dit alsnog veranderen).",
    ]
    if r.archief_doorzocht:
        text_delen.append(
            f"- Afgelopen 12 mnd te koop geweest (voor zover in ons archief): "
            f"{len(r.pool_te_koop_geweest)}."
        )
    else:
        text_delen.append(
            "- Te-koop-geweest: archief wordt nog opgebouwd, dus deze keer niet meegenomen."
        )
    text_delen += [
        "",
        _lijst_txt("Afgevallen - opkoopbescherming", r.afgevallen_opkoop, met_woz=True),
        "",
        _lijst_txt("Afgevallen - binnen 50 m van bestaande vergunning", r.afgevallen_50m),
        "",
        "Kanttekening: lopende, nog niet verwerkte vergunningaanvragen (doorlooptijd "
        "~14 weken) zijn niet zichtbaar - Rotterdam publiceert kamerverhuur-aanvragen "
        "niet, alleen de uiteindelijke beslissing.",
        "",
        "Bron: adressen/coördinaten via PDOK, WOZ via het WOZ-waardeloket, oppervlakte "
        "via BAG, 50 m-norm via de officiele Rotterdamse vergunningenkaart.",
    ]
    text = "\n".join(text_delen)

    # ---------- htmlversie ----------
    def _lijst_html(titel, rijen, met_woz=False, met_m2=False, met_tekoop=False):
        koppen = ["Adres", "Afstand"]
        if met_woz:
            koppen.append("WOZ")
        if met_m2:
            koppen.append("BAG m²")
        if met_tekoop:
            koppen.append("Te koop gezien")
        thead = "".join(f"<th style='text-align:left'>{k}</th>" for k in koppen)
        rows = ""
        for a in sorted(rijen, key=lambda x: x.afstand_m):
            cellen = [a.weergavenaam, f"{a.afstand_m:.0f} m"]
            if met_woz:
                cellen.append(_eur(a.woz))
            if met_m2:
                cellen.append(_m2(a.bag_m2))
            if met_tekoop:
                cellen.append(a.te_koop_laatst or "-")
            rows += "<tr>" + "".join(f"<td>{c}</td>" for c in cellen) + "</tr>"
        return (f"<h3>{titel} ({len(rijen)})</h3>"
                f"<table cellpadding='4' style='border-collapse:collapse'>"
                f"<tr>{thead}</tr>{rows}</table>")

    html_delen = [f"<h2>Concurrentie-scan rond {r.centrum_adres}</h2>",
                  f"<p>Straal: {r.straal_m:.0f} m &middot; WOZ-grens opkoop: {_eur(r.grens)} "
                  f"&middot; m²-grens 4 kamers: {r.m2_grens} m²</p>"]
    if waarschuwingen:
        html_delen.append("<p style='color:#b00'><b>Let op:</b><br>"
                          + "<br>".join(waarschuwingen) + "</p>")
    html_delen += [
        "<ol>",
        f"<li>Adressen binnen {r.straal_m:.0f} m: <b>{len(r.rijen)}</b></li>",
        f"<li>{opkoop_regel}</li>",
        f"<li>50 m-norm: <b>{len(r.afgevallen_50m)}</b> adres(sen) vallen af "
        "(binnen 50 m van een bestaande vergunning).</li>",
        "</ol>",
        f"<p><b>Overgebleven pool: {len(pool)}</b> adres(sen) waar theoretisch nog een "
        "4+-aanvraag op zou kunnen liggen.</p>",
        "<ul>",
        f"<li>Krap voor 4 kamers (BAG &lt; {r.m2_grens} m²): <b>{len(r.pool_te_klein)}</b> "
        "<i>(niet uitgesloten - na een dakkapel/aanbouw kan dit veranderen)</i></li>",
    ]
    if r.archief_doorzocht:
        html_delen.append(
            f"<li>Afgelopen 12 mnd te koop geweest (voor zover in ons archief): "
            f"<b>{len(r.pool_te_koop_geweest)}</b></li>"
        )
    else:
        html_delen.append(
            "<li>Te-koop-geweest: archief wordt nog opgebouwd, deze keer niet meegenomen.</li>"
        )
    html_delen += [
        "</ul>",
        _lijst_html("Pool (overgebleven)", pool, met_woz=r.in_opkoopwijk, met_m2=True,
                    met_tekoop=r.archief_doorzocht),
        _lijst_html("Afgevallen - opkoopbescherming", r.afgevallen_opkoop, met_woz=True),
        _lijst_html("Afgevallen - binnen 50 m van bestaande vergunning", r.afgevallen_50m),
        "<p style='color:#888;font-size:.85em'>Kanttekening: lopende, nog niet verwerkte "
        "aanvragen (doorlooptijd ~14 weken) zijn niet zichtbaar - Rotterdam publiceert "
        "kamerverhuur-aanvragen niet, alleen de beslissing.<br>"
        "Bron: PDOK (adressen/coördinaten), WOZ-waardeloket, BAG (oppervlakte), "
        "officiele Rotterdamse vergunningenkaart (50 m-norm).</p>",
    ]
    html = "".join(html_delen)

    return onderwerp, html, text
