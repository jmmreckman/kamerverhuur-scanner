"""Opkoopbescherming-scan: tel binnen een 50 m-straal rond een adres hoeveel
woningen een WOZ-waarde bóven de opkoopbescherming-grens hebben en hoeveel eronder.

Doel: inschatten hoeveel concurrentie er is voor mogelijke (kamerverhuur-)vergunning-
aanvragen. Woningen met een WOZ onder de grens vallen onder opkoopbescherming
(zelfbewoningsplicht - lastiger als belegging op te pakken); woningen boven de grens
zijn vrij verhandelbaar en dus eerder potentiële concurrentie.

Databronnen:
- adressen binnen de straal: PDOK locatieserver (reverse) - zie geocode.adressen_binnen_straal.
- WOZ-waarde per adres: de publieke LV-WOZ achter het WOZ-waardeloket
  (api.kadaster.nl/lvwoz/...). Alleen individuele raadplegingen, met een korte pauze
  tussen de calls zodat we de dienst netjes belasten.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

from . import geocode

WOZ_API = "https://api.kadaster.nl/lvwoz/wozwaardeloket-api/v1"


def woz_waarde(nummeraanduiding_id: str, *, timeout: int = 15) -> int | None:
    """Meest recente vastgestelde WOZ-waarde (in hele euro's) voor een
    nummeraanduiding, of None als er geen waarde te vinden is (bv. een niet-woning,
    of een tijdelijke fout bij de WOZ-dienst)."""
    url = f"{WOZ_API}/wozwaarde/nummeraanduiding/{nummeraanduiding_id}"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except (requests.exceptions.RequestException, ValueError):
        return None
    waarden = data.get("wozWaarden") or []
    recent = max(waarden, key=lambda w: w.get("peildatum", ""), default=None)
    if not recent:
        return None
    waarde = recent.get("vastgesteldeWaarde")
    try:
        return int(waarde) if waarde is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class AdresResultaat:
    weergavenaam: str
    afstand_m: float
    woz: int | None  # None = geen WOZ gevonden (onbekend)


@dataclass
class ScanResultaat:
    centrum_adres: str
    straal_m: float
    grens: int
    adressen: list[AdresResultaat] = field(default_factory=list)

    @property
    def met_woz(self) -> list[AdresResultaat]:
        return [a for a in self.adressen if a.woz is not None]

    @property
    def boven(self) -> list[AdresResultaat]:
        return [a for a in self.adressen if a.woz is not None and a.woz > self.grens]

    @property
    def onder(self) -> list[AdresResultaat]:
        return [a for a in self.adressen if a.woz is not None and a.woz <= self.grens]

    @property
    def onbekend(self) -> list[AdresResultaat]:
        return [a for a in self.adressen if a.woz is None]

    @property
    def pct_boven(self) -> float:
        n = len(self.met_woz)
        return round(100 * len(self.boven) / n, 1) if n else 0.0

    @property
    def pct_onder(self) -> float:
        n = len(self.met_woz)
        return round(100 * len(self.onder) / n, 1) if n else 0.0


def scan(lat: float, lon: float, grens: int, centrum_adres: str, *,
         straal_m: float = 50.0, pauze_s: float = 0.15,
         woz_func=woz_waarde, adres_func=None) -> ScanResultaat:
    """Voert de scan uit: adressen binnen de straal ophalen en per adres de WOZ.
    `woz_func`/`adres_func` zijn injecteerbaar zodat de logica los te testen is
    zonder echte PDOK/WOZ-calls."""
    adres_func = adres_func or geocode.adressen_binnen_straal
    nabij = adres_func(lat, lon, straal_m)
    resultaat = ScanResultaat(centrum_adres=centrum_adres, straal_m=straal_m, grens=grens)
    for i, a in enumerate(nabij):
        if i and pauze_s:
            time.sleep(pauze_s)  # beleefd tegen de WOZ-dienst
        resultaat.adressen.append(
            AdresResultaat(weergavenaam=a.weergavenaam, afstand_m=a.afstand_m,
                           woz=woz_func(a.nummeraanduiding_id))
        )
    return resultaat


def _eur(bedrag: int | None) -> str:
    if bedrag is None:
        return "onbekend"
    return "€" + format(bedrag, ",d").replace(",", ".")


def bouw_mail(r: ScanResultaat) -> tuple[str, str, str]:
    """Geeft (onderwerp, html_body, text_body) voor de resultaatmail."""
    grens = _eur(r.grens)
    onderwerp = (
        f"Opkoopbescherming-scan {r.centrum_adres}: "
        f"{len(r.boven)} boven / {len(r.onder)} onder grens ({r.pct_boven}% boven)"
    )

    def _lijst_txt(titel, items):
        regels = [f"{titel} ({len(items)}):"]
        for a in sorted(items, key=lambda x: x.afstand_m):
            regels.append(f"  - {a.weergavenaam} | {a.afstand_m:.0f} m | WOZ {_eur(a.woz)}")
        return "\n".join(regels)

    text = "\n".join([
        f"Opkoopbescherming-scan rond: {r.centrum_adres}",
        f"Straal: {r.straal_m:.0f} m | Grens: {grens}",
        "",
        f"Adressen binnen de straal: {len(r.adressen)} "
        f"(met WOZ-waarde: {len(r.met_woz)}, onbekend: {len(r.onbekend)})",
        f"BOVEN de grens (vrij verhandelbaar, potentiële concurrentie): "
        f"{len(r.boven)}  ({r.pct_boven}% van de adressen met WOZ)",
        f"ONDER de grens (opkoopbescherming, zelfbewoningsplicht): "
        f"{len(r.onder)}  ({r.pct_onder}%)",
        "",
        _lijst_txt("BOVEN de grens", r.boven),
        "",
        _lijst_txt("ONDER de grens", r.onder),
        "",
        _lijst_txt("WOZ onbekend (niet meegeteld in de percentages)", r.onbekend),
        "",
        "Bron: adressen via PDOK, WOZ-waarden via het WOZ-waardeloket (LV-WOZ).",
    ])

    def _lijst_html(titel, items):
        rijen = "".join(
            f"<tr><td>{a.weergavenaam}</td><td style='text-align:right'>{a.afstand_m:.0f} m</td>"
            f"<td style='text-align:right'>{_eur(a.woz)}</td></tr>"
            for a in sorted(items, key=lambda x: x.afstand_m)
        )
        return (f"<h3>{titel} ({len(items)})</h3>"
                f"<table cellpadding='4' style='border-collapse:collapse'>{rijen}</table>")

    html = "".join([
        f"<h2>Opkoopbescherming-scan rond {r.centrum_adres}</h2>",
        f"<p>Straal: {r.straal_m:.0f} m &middot; Grens: {grens}</p>",
        "<ul>",
        f"<li>Adressen binnen de straal: <b>{len(r.adressen)}</b> "
        f"(met WOZ: {len(r.met_woz)}, onbekend: {len(r.onbekend)})</li>",
        f"<li><b>Boven</b> de grens (vrij verhandelbaar, potentiële concurrentie): "
        f"<b>{len(r.boven)}</b> ({r.pct_boven}%)</li>",
        f"<li><b>Onder</b> de grens (opkoopbescherming): <b>{len(r.onder)}</b> ({r.pct_onder}%)</li>",
        "</ul>",
        _lijst_html("Boven de grens", r.boven),
        _lijst_html("Onder de grens", r.onder),
        _lijst_html("WOZ onbekend", r.onbekend),
        "<p style='color:#888;font-size:.85em'>Bron: adressen via PDOK, "
        "WOZ-waarden via het WOZ-waardeloket (LV-WOZ).</p>",
    ])

    return onderwerp, html, text
