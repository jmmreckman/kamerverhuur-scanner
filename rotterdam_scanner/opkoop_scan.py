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

import requests

from . import bag, gis, opkoop, woz
from . import geocode

# Minimale gebruiksoppervlakte voor 4 bewoners: 4 × 18 m² (norm 18 m²/persoon).
# Alleen ter vermelding - niet om hard uit te sluiten (na een dakkapel/aanbouw kan een
# krap pand alsnog aan de maat komen).
GRENS_M2_4KAMERS = 72


def _norm_adres(weergavenaam: str) -> str:
    """Genormaliseerde adrestekst (lowercase, witruimte samengevouwen) om het
    centrumadres te matchen tegen de buuradressen - beide komen uit PDOK."""
    return " ".join((weergavenaam or "").lower().split())


def _veilige_woz(nummeraanduiding_id: str, *, pogingen: int = 3) -> int | None:
    """Meest recente WOZ-waarde, of None. None = geen openbare WOZ (bv. een niet-woning:
    het loket geeft dan een 404, wat woz.fetch als lege lijst teruggeeft) OF het ophalen
    is na alle retries blijven haken.

    Retries met backoff zijn belangrijk: bij ~100 WOZ-calls achter elkaar op de VPS
    mislukt er af en toe één op een tijdelijke time-out/5xx; zonder retry zou die woning
    stilletjes als 'WOZ onbekend' in de pool belanden i.p.v. correct af te vallen op de
    opkoopgrens. Een 404 (geen WOZ) levert géén exception op en wordt dus niet geretry'd."""
    for i in range(pogingen):
        try:
            w = woz.meest_recente_woz_waarde(nummeraanduiding_id)
            return w.bedrag if w else None
        except requests.exceptions.RequestException:
            if i < pogingen - 1:
                time.sleep(1.5 * (i + 1))  # 1,5s, 3s
    return None


def _veilige_bag(adresseerbaarobject_id: str) -> tuple[int | None, str | None]:
    """(oppervlakte, gebruiksdoel) uit de BAG, of (None, None) bij een storing."""
    try:
        g = bag.fetch_bag_gegevens(adresseerbaarobject_id)
        return (g.oppervlakte, g.gebruiksdoel) if g else (None, None)
    except Exception:
        return (None, None)


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
    gebruiksdoel: str | None = None
    binnen_50m: bool | None = None
    te_koop_laatst: str | None = None       # ISO-datum, laatst te koop gezien (binnen 12 mnd)
    te_koop_sinds: str | None = None        # ISO-datum, vroegst te koop gezien
    te_koop_prijs: int | None = None        # laatst bekende vraagprijs
    te_koop_bron: str | None = None         # "funda" / "nvm" (evt. beide)
    te_koop_url: str | None = None          # advertentie-URL (voor handmatig onderzoek)
    te_koop_status: str | None = None       # laatst bekende status (actief / afgevallen)
    reden_afgevallen: str | None = None      # None = nog in de pool

    @property
    def woz_onbekend(self) -> bool:
        return self.woz is None

    @property
    def nu_te_koop(self) -> bool:
        """Staat volgens de laatst bekende status nú nog te koop (actieve listing),
        i.p.v. inmiddels verkocht/van de markt - het scherpste risico."""
        return (self.te_koop_status or "").lower() == "actief"


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

    # --- uitgesloten categorieën (reden_afgevallen is gezet) ---
    @property
    def centrum_rijen(self) -> list[AdresRij]:
        """Het centrumadres zelf (jouw doeladres) - uitgesloten van de concurrentie."""
        return [r for r in self.rijen if r.reden_afgevallen == "centrumadres"]

    @property
    def afgevallen_opkoop(self) -> list[AdresRij]:
        return [r for r in self.rijen if r.reden_afgevallen and r.reden_afgevallen.startswith("opkoop")]

    @property
    def afgevallen_50m(self) -> list[AdresRij]:
        return [r for r in self.rijen if r.reden_afgevallen and "50 m" in r.reden_afgevallen]

    @property
    def zeer_onwaarschijnlijk(self) -> list[AdresRij]:
        """Ander gebruiksdoel dan wonen (kantoor/winkel/industrie/bijeenkomst/...):
        kamerverhuur is daar zeer onwaarschijnlijk."""
        return [r for r in self.rijen if r.reden_afgevallen and r.reden_afgevallen.startswith("ander gebruiksdoel")]

    @property
    def pool(self) -> list[AdresRij]:
        """Alle overgebleven woningen (niet uitgesloten door gebruiksdoel, opkoop of
        de 50 m-norm). Splitst verder in pool_reeel + pool_te_klein."""
        return [r for r in self.rijen if r.reden_afgevallen is None]

    @property
    def pool_te_klein(self) -> list[AdresRij]:
        """Woningen onder de m²-grens: waarschijnlijk geen gevaar (te klein voor 4
        kamers), maar NIET hard uitgesloten - een dakkapel/aanbouw kan dit nog
        veranderen."""
        return [r for r in self.pool if r.bag_m2 is not None and r.bag_m2 < self.m2_grens]

    @property
    def pool_reeel(self) -> list[AdresRij]:
        """De reële concurrentiepool: woningen die groot genoeg zijn (of waarvan de
        oppervlakte onbekend is) en alle filters hebben overleefd."""
        return [r for r in self.pool if r.bag_m2 is None or r.bag_m2 >= self.m2_grens]

    @property
    def pool_te_koop_geweest(self) -> list[AdresRij]:
        return [r for r in self.pool if r.te_koop_laatst]

    @property
    def grootste_risicos(self) -> list[AdresRij]:
        """De topkandidaten voor handmatig onderzoek: in de reële pool (viabel voor een
        4+-vergunning) én de afgelopen 12 mnd te koop geweest. Meest recent te koop
        bovenaan."""
        risicos = [r for r in self.pool_reeel if r.te_koop_laatst]
        # Nu-nog-te-koop bovenaan (scherpste risico), daarna op recentheid.
        return sorted(risicos, key=lambda r: (r.nu_te_koop, r.te_koop_laatst or ""), reverse=True)


def scan(lat: float, lon: float, grens: int, centrum_adres: str, *,
         straal_m: float = 50.0, m2_grens: int = GRENS_M2_4KAMERS, pauze_s: float = 0.1,
         adres_func=None, woz_func=_veilige_woz, bag_func=_veilige_bag,
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

    # Het centrumadres zelf (jouw doeladres) is geen concurrentie - sluit het meteen uit
    # zodat het nergens in de pool/risico's opduikt. Match op genormaliseerde adrestekst
    # (beide uit PDOK, dus dezelfde schrijfwijze).
    centrum_norm = _norm_adres(centrum_adres)
    for r in rijen:
        if centrum_norm and _norm_adres(r.weergavenaam) == centrum_norm:
            r.reden_afgevallen = "centrumadres"

    resultaat = ScanResultaat(
        centrum_adres=centrum_adres, straal_m=straal_m, grens=grens, m2_grens=m2_grens,
        buurtnaam=buurtnaam, in_opkoopwijk=in_opkoopwijk, rijen=rijen,
        archief_doorzocht=te_koop_func is not None,
    )

    # Stap 2 - opkoopbescherming (alleen zinvol in een beschermde wijk). Al uitgesloten
    # adressen (zoals het centrumadres) slaan we over.
    if in_opkoopwijk:
        te_checken = [r for r in rijen if r.reden_afgevallen is None]
        geen_enkele_woz = True
        for i, r in enumerate(te_checken):
            if i and pauze_s:
                time.sleep(pauze_s)
            r.woz = woz_func(r.nummeraanduiding_id)
            if r.woz is not None:
                geen_enkele_woz = False
                if r.woz <= grens:
                    r.reden_afgevallen = "opkoopbescherming (WOZ ≤ grens)"
        if geen_enkele_woz and te_checken:
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

    # Stap 4 - BAG (oppervlakte + gebruiksdoel) op de overgebleven adressen. Een ander
    # gebruiksdoel dan wonen (kantoor/winkel/industrie/bijeenkomst/...) valt hier af
    # naar "zeer onwaarschijnlijk": kamerverhuur is daar hoogst onwaarschijnlijk (en er
    # is ook geen openbare WOZ, vandaar dat zo'n pand de opkoopstap overleefde).
    for i, r in enumerate([r for r in rijen if r.reden_afgevallen is None]):
        if i and pauze_s:
            time.sleep(pauze_s)
        r.bag_m2, r.gebruiksdoel = bag_func(r.adresseerbaarobject_id)
        if r.gebruiksdoel and "woonfunctie" not in r.gebruiksdoel:
            r.reden_afgevallen = f"ander gebruiksdoel ({r.gebruiksdoel})"

    # Stap 5 - te-koop-geweest (vermelding) op de resterende woning-pool.
    if te_koop_func is not None:
        grens_datum = (vandaag - timedelta(days=365)).isoformat()
        for r in resultaat.pool:
            info = te_koop_func(r.weergavenaam, grens_datum)
            if not info:
                continue
            if isinstance(info, str):      # eenvoudige bron/fake: alleen een datum
                r.te_koop_laatst = info
            else:                          # volledige info-dict (zie archief.bouw_te_koop_index)
                r.te_koop_laatst = info.get("tot")
                r.te_koop_sinds = info.get("sinds")
                r.te_koop_prijs = info.get("prijs")
                r.te_koop_bron = info.get("bron")
                r.te_koop_url = info.get("url")
                r.te_koop_status = info.get("status")

    return resultaat


def korte_samenvatting(r: ScanResultaat) -> str:
    """Eén-zins-samenvatting van de concurrentie-scan, voor in het kaart-popup van een
    favoriete woning."""
    reeel = r.pool_reeel
    nu = sum(1 for a in reeel if a.nu_te_koop)
    risico = len(r.grootste_risicos)
    delen = [f"{len(reeel)} reële concurrent(en) binnen {r.straal_m:.0f} m"]
    if nu:
        delen.append(f"{nu} nu te koop")
    if risico:
        delen.append(f"{risico} recent te koop geweest")
    staart = []
    if r.pool_te_klein:
        staart.append(f"{len(r.pool_te_klein)} te klein")
    if r.zeer_onwaarschijnlijk:
        staart.append(f"{len(r.zeer_onwaarschijnlijk)} ander gebruiksdoel")
    zin = ", waarvan ".join([delen[0], "; ".join(delen[1:])]) if len(delen) > 1 else delen[0]
    if staart:
        zin += " (" + ", ".join(staart) + ")"
    return zin + "."


def _eur(bedrag: int | None) -> str:
    if bedrag is None:
        return "onbekend"
    return "€" + format(bedrag, ",d").replace(",", ".")


def _m2(waarde: int | None) -> str:
    return f"{waarde} m²" if waarde is not None else "onbekend"


_KANTTEKENING = (
    "Lopende, nog niet verwerkte vergunningaanvragen (doorlooptijd ~14 weken) zijn "
    "niet zichtbaar - Rotterdam publiceert kamerverhuur-aanvragen niet, alleen de "
    "uiteindelijke beslissing."
)


def bouw_cover(r: ScanResultaat) -> tuple[str, str, str]:
    """Korte begeleidende e-mailtekst (onderwerp, html, text). De volledige
    adreslijsten zitten in het bijgevoegde PDF-rapport (zie bouw_rapport_pdf), zodat
    de mail zelf overzichtelijk blijft."""
    reeel = r.pool_reeel
    onderwerp = (
        f"Concurrentie-scan {r.centrum_adres}: "
        f"{len(reeel)} reële adressen binnen {r.straal_m:.0f} m"
    )

    waarschuwingen = []
    if r.woz_onbereikbaar:
        waarschuwingen.append(
            "De WOZ-dienst gaf geen enkele waarde terug (tijdelijk onbereikbaar); de "
            "opkoopbescherming-stap kon daardoor niet betrouwbaar draaien."
        )
    if r.gis_onbereikbaar:
        waarschuwingen.append(
            "De Rotterdamse vergunningenkaart (ArcGIS) was niet bereikbaar; de "
            "50 m-norm-stap kon daardoor niet draaien."
        )

    opkoop_regel = (
        f"Afgevallen door opkoopbescherming (WOZ ≤ {_eur(r.grens)}): {len(r.afgevallen_opkoop)}"
        if r.in_opkoopwijk else
        f"Niet in een opkoopbescherming-wijk ('{r.buurtnaam}') - hierop valt niets af"
    )

    text = "\n".join([
        f"Concurrentie-scan rond: {r.centrum_adres}",
        f"Straal: {r.straal_m:.0f} m | WOZ-grens opkoop: {_eur(r.grens)} | "
        f"m²-grens 4 kamers: {r.m2_grens} m²",
        "",
        *(["LET OP:"] + [f"- {w}" for w in waarschuwingen] + [""] if waarschuwingen else []),
        "Samenvatting:",
        f"- Adressen binnen {r.straal_m:.0f} m: {len(r.rijen)}",
        f"- {opkoop_regel}",
        f"- Afgevallen door de 50 m-norm: {len(r.afgevallen_50m)}",
        f"- Zeer onwaarschijnlijk (ander gebruiksdoel dan wonen): {len(r.zeer_onwaarschijnlijk)}",
        f"- Waarschijnlijk geen gevaar - te klein (< {r.m2_grens} m², check dakkapel): "
        f"{len(r.pool_te_klein)}",
        f"=> REËLE concurrentiepool: {len(reeel)} adres(sen) waar theoretisch nog een "
        "4+-aanvraag op zou kunnen liggen",
        f"=> GROOTSTE RISICO'S (reële pool + afgelopen 12 mnd te koop geweest): "
        f"{len(r.grootste_risicos)} - deze staan bovenaan in de PDF om handmatig uit te zoeken",
        "",
        "Het volledige rapport met alle adreslijsten (reële pool, de te-kleine en "
        "andere-gebruiksdoel-adressen, en de afvallers) zit in de bijgevoegde PDF.",
        "",
        _KANTTEKENING,
    ])

    html_delen = [
        f"<h2 style='margin:0 0 .3rem'>Concurrentie-scan rond {r.centrum_adres}</h2>",
        f"<p style='color:#555;margin:0 0 1rem'>Straal: {r.straal_m:.0f} m &middot; "
        f"WOZ-grens opkoop: {_eur(r.grens)} &middot; m²-grens 4 kamers: {r.m2_grens} m²</p>",
    ]
    if waarschuwingen:
        html_delen.append("<p style='color:#b00'><b>Let op:</b><br>"
                          + "<br>".join(waarschuwingen) + "</p>")
    html_delen += [
        "<ul>",
        f"<li>Adressen binnen {r.straal_m:.0f} m: <b>{len(r.rijen)}</b></li>",
        f"<li>{opkoop_regel}</li>",
        f"<li>Afgevallen door de 50 m-norm: <b>{len(r.afgevallen_50m)}</b></li>",
        f"<li>Zeer onwaarschijnlijk (ander gebruiksdoel): <b>{len(r.zeer_onwaarschijnlijk)}</b></li>",
        f"<li>Waarschijnlijk geen gevaar - te klein (&lt; {r.m2_grens} m², check dakkapel): "
        f"<b>{len(r.pool_te_klein)}</b></li>",
        f"<li><b>Reële concurrentiepool: {len(reeel)}</b> adres(sen) waar theoretisch nog "
        "een 4+-aanvraag op zou kunnen liggen</li>",
        f"<li style='color:#b00'><b>Grootste risico's: {len(r.grootste_risicos)}</b> "
        "(reële pool + afgelopen 12 mnd te koop geweest) - staan bovenaan in de PDF om "
        "handmatig uit te zoeken</li>",
        "</ul>",
        "<p>Het volledige rapport met alle adreslijsten zit in de "
        "<b>bijgevoegde PDF</b>.</p>",
        f"<p style='color:#888;font-size:.85em'>{_KANTTEKENING}</p>",
    ]
    html = "".join(html_delen)
    return onderwerp, html, text
