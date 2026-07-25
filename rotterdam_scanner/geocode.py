from __future__ import annotations

import re
from dataclasses import dataclass

import requests

PDOK_FREE_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"

_RD_POINT_RE = re.compile(r"POINT\(([-\d.]+) ([-\d.]+)\)")
# WGS84 (lon/lat, in die volgorde binnen de WKT POINT) - voor de kaart op
# kansen.steenhub.nl. Los van _RD_POINT_RE omdat een ontbrekende centroide_ll
# niet fataal hoeft te zijn (de rest van de pipeline heeft alleen de
# RD-coördinaten nodig), in tegenstelling tot een ontbrekende centroide_rd.
_LL_POINT_RE = re.compile(r"POINT\(([-\d.]+) ([-\d.]+)\)")


class GeocodeError(RuntimeError):
    """Adres kon niet eenduidig worden opgezocht via PDOK."""


@dataclass(frozen=True)
class GeocodeResult:
    weergavenaam: str
    straatnaam: str
    huisnummer: str
    postcode: str
    woonplaats: str
    # PDOK "wijknaam" is het CBS-wijkniveau (grover, bijv. "Delfshaven"). De namen die de
    # gemeente Rotterdam zelf hanteert voor haar beleid (opkoopbescherming, nulquotum, o.a.
    # "Middelland", "Bloemhof") komen overeen met het fijnere CBS-"buurt"-niveau, dus dat is
    # het veld dat we voor de opkoopbescherming-check gebruiken.
    rotterdam_wijk: str
    cbs_wijknaam: str
    rd_x: float
    rd_y: float
    lon: float | None
    lat: float | None
    nummeraanduiding_id: str
    adresseerbaarobject_id: str


def _doc_naar_resultaat(doc: dict, fallback_naam: str) -> GeocodeResult:
    rd_match = _RD_POINT_RE.match(doc.get("centroide_rd", ""))
    if not rd_match:
        raise GeocodeError(f"Geen RD-coördinaat in PDOK-resultaat voor '{fallback_naam}'")

    ll_match = _LL_POINT_RE.match(doc.get("centroide_ll", ""))

    return GeocodeResult(
        weergavenaam=doc.get("weergavenaam", fallback_naam),
        straatnaam=doc.get("straatnaam", ""),
        huisnummer=str(doc.get("huis_nlt", "")),
        postcode=doc.get("postcode", ""),
        woonplaats=doc.get("woonplaatsnaam", ""),
        rotterdam_wijk=doc.get("buurtnaam", ""),
        cbs_wijknaam=doc.get("wijknaam", ""),
        rd_x=float(rd_match.group(1)),
        rd_y=float(rd_match.group(2)),
        lon=float(ll_match.group(1)) if ll_match else None,
        lat=float(ll_match.group(2)) if ll_match else None,
        nummeraanduiding_id=doc.get("nummeraanduiding_id", ""),
        adresseerbaarobject_id=doc.get("adresseerbaarobject_id", ""),
    )


def _zoek_pdok_adres(query: str, extra_filters: list[str]) -> dict:
    params = {
        "q": query,
        "rows": 1,
        "fq": ["type:adres", *extra_filters],
    }
    resp = requests.get(PDOK_FREE_URL, params=params, timeout=15)
    resp.raise_for_status()
    docs = resp.json().get("response", {}).get("docs", [])
    if not docs:
        raise GeocodeError(f"Geen PDOK-match voor '{query}'")
    return docs[0]


def geocode_by_postcode(postcode: str, huisnummer: str, toevoeging: str = "") -> GeocodeResult:
    """Zoekt een adres op via postcode + huisnummer(+toevoeging) -- dit is ondubbelzinnig
    (elke combinatie hoort bij precies één adres in Nederland) en dus betrouwbaarder dan
    zoeken op straatnaam, waar gelijkende straatnamen in andere wijken toe kunnen leiden."""
    postcode_kaal = postcode.replace(" ", "").upper()
    # Een koppelteken tussen huisnummer en toevoeging is nodig voor PDOK om ze correct
    # uit elkaar te houden -- zonder koppelteken matcht een toevoeging die met een cijfer
    # begint (bijv. "02L" bij een portiekwoning) soms stilzwijgend het verkeerde adres in
    # plaats van een fout te geven.
    huisnummer_volledig = f"{huisnummer}-{toevoeging}" if toevoeging else huisnummer
    query = f"{postcode_kaal} {huisnummer_volledig}"
    doc = _zoek_pdok_adres(query, [f"postcode:{postcode_kaal}"])
    return _doc_naar_resultaat(doc, query)


def geocode_address(straat: str, huisnummer: str, woonplaats: str = "Rotterdam") -> GeocodeResult:
    query = f"{straat} {huisnummer}, {woonplaats}"
    doc = _zoek_pdok_adres(query, [f"woonplaatsnaam:{woonplaats}"])
    return _doc_naar_resultaat(doc, query)
