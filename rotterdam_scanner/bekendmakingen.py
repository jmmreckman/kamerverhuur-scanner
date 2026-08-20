"""Vroege waarschuwing voor nieuwe kamerverhuurvergunningen bij je favoriete panden.

De gemeente publiceert een verleende kamerverhuurvergunning eerst als officiële
bekendmaking (Gemeenteblad, doorzoekbaar via zoek.officielebekendmakingen.nl)
en pas later op haar eigen kaartlaag - de laag die rotterdam_scanner/gis.py
raadpleegt voor de 50-meter-check. Wie net een pand koopt, wil dat verschil niet
missen: een nieuwe vergunning binnen 50 m raakt de eigen vergunningskansen
(nulquotum/afstandseis).

Daarom monitort deze module de officiële bekendmakingen (via de machine-leesbare
KOOP SRU-zoekdienst) op nieuwe "Vergunning kamerverhuur <adres>"-publicaties,
geocodeert dat adres (PDOK, net als de rest van de pipeline) en checkt of het
binnen 50 m van een als favoriet gemarkeerde woning ligt. Zo ja: er komt een
waarschuwing bij de woning én (via pipeline.run) een mail. Elke publicatie wordt
per pand maar één keer als waarschuwing opgeslagen, dus je krijgt nooit twee keer
dezelfde melding.
"""
from __future__ import annotations

import json
import logging
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import requests

from .geocode import GeocodeError, geocode_vrij

logger = logging.getLogger(__name__)

# Machine-leesbare zoekdienst achter zoek.officielebekendmakingen.nl (de gewone
# ?q=-webpagina blokkeert geautomatiseerde requests; deze SRU-endpoint niet).
SRU_URL = "https://repository.overheid.nl/sru"

# Afstand waarbinnen een verleende kamerverhuurvergunning relevant is voor een
# favoriet pand - gelijk aan de 50 m-invloedscirkel die de gemeente zelf om elke
# vergunning legt (zie rotterdam_scanner/gis.py).
STRAAL_METER = 50.0

# Hoe ver we elke run terugkijken in de bekendmakingen. Ruim groter dan de
# dagelijkse scan-interval, zodat een gemiste dag (container-herstart, storing bij
# KOOP) geen publicatie laat wegvallen - dubbele treffers worden er per pand toch
# op publicatie-id uitgefilterd.
TERUGKIJK_DAGEN = 60

# De 50 m-afstandseis van Rotterdam telt alléén reeds verleende vergunningen voor
# 4 of méér kamerbewoners (Verordening samenstelling Woningvoorraad 2025, art.
# 2.2.3 lid 1 sub b + lid 2). Een 3-persoonsvergunning legt geen 50 m-zone op en is
# dus niet relevant voor de vroege waarschuwing bij favorieten - die filteren we
# eruit. Onbekend aantal (body niet te parsen) laten we conservatief wél
# waarschuwen, om nooit een echte 4+ te missen.
MIN_KAMERBEWONERS_VOOR_AFSTANDSEIS = 4

# Zoektermen waaronder de per-adres vergunningen verschijnen. Rotterdam titelt ze
# tegenwoordig "Vergunning kamerverhuur ..."; "kamerbewoning" vangt oudere en
# afwijkende formuleringen af. Beleidsregels/verordeningen die op deze termen ook
# terugkomen worden verderop weggefilterd omdat hun titel geen adres bevat.
_ZOEKTERMEN = ("kamerverhuur", "kamerbewoning")

# Per stad: de publicerende gemeente (dt.creator in de SRU-query) en de woonplaats
# waarmee het adres uit de titel geocodeerd wordt.
_STAD_CONFIG = {
    "rotterdam": {"creator": "Rotterdam", "woonplaats": "Rotterdam"},
    "den_haag": {"creator": "'s-Gravenhage", "woonplaats": "Den Haag"},
}

_NS = {
    "sru": "http://docs.oasis-open.org/ns/search-ws/sruResponse",
    "dcterms": "http://purl.org/dc/terms/",
    "gzd": "http://standaarden.overheid.nl/sru",
}
_GZD_TAG = "{http://standaarden.overheid.nl/sru}gzd"

# Titelvorm van een verleende vergunning: "Vergunning kamerverhuur <adres>". De
# adrestekst is alles daarachter.
_TITEL_RE = re.compile(
    r"^\s*vergunning\s+kamer(?:verhuur|bewoning)\s+(?P<adres>.+?)\s*$", re.IGNORECASE
)
# Titels die géén geldende vergunning-op-adres zijn: een intrekking/weigering legt
# juist geen 50 m-beperking op; een algemene beleidsregel heeft geen specifiek
# adres (en zou zonder deze filter mogelijk op een verkeerd adres geocoderen).
_UITSLUIT_RE = re.compile(
    r"intrekking|ingetrokken|weiger|geweigerd|buiten behandeling|beleidsregel|verordening|aanvraag|aanvragen",
    re.IGNORECASE,
)
# "- Rectificatie"/"- Correctie" achter het adres weghalen vóór het geocoderen
# (het blijft een verleende vergunning, alleen met gecorrigeerde tekst).
_SUFFIX_RE = re.compile(r"\s*[-–]\s*(rectificatie|correctie|herstel).*$", re.IGNORECASE)


@dataclass
class Vergunning:
    publicatie_id: str  # bv. "gmb-2026-12345"
    titel: str
    datum: str  # ISO-datum
    url: str
    adres: str
    stad: str
    lat: float | None = None
    lon: float | None = None
    html_url: str | None = None
    aantal_personen: int | None = None


def _pub_id(url: str) -> str:
    """.../gmb-2026-12345.html -> gmb-2026-12345 (stabiele, unieke publicatie-sleutel)."""
    naam = url.rstrip("/").rsplit("/", 1)[-1]
    return naam[:-5] if naam.endswith(".html") else naam


def _adres_uit_titel(titel: str) -> str | None:
    if _UITSLUIT_RE.search(titel):
        return None
    match = _TITEL_RE.match(titel)
    if not match:
        return None
    adres = _SUFFIX_RE.sub("", match.group("adres")).strip()
    return adres or None


def _haal_sru(term: str, creator: str, cutoff: date, max_records: int = 200) -> list[dict]:
    """Rauwe SRU-treffers (titel/datum/url) voor één zoekterm + gemeente vanaf de
    cutoff-datum. De SRU-dienst negeert sortKeys voor deze index, dus we filteren
    op datum via CQL (dt.date>=...) i.p.v. te sorteren - dat houdt de resultaatset
    klein en actueel."""
    query = (
        f"(cql.textAndIndexes={term}) and (dt.creator={creator}) "
        f"and (dt.date>={cutoff.isoformat()})"
    )
    params = {
        "operation": "searchRetrieve",
        "version": "2.0",
        "x-connection": "BEK",
        "query": query,
        "maximumRecords": str(max_records),
        "recordSchema": "gzd",
    }
    resp = requests.get(SRU_URL, params=params, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)

    records = []
    for rec in root.iter(_GZD_TAG):
        titel = rec.find(".//dcterms:title", _NS)
        datum = rec.find(".//dcterms:date", _NS)
        url = rec.find(".//gzd:preferredUrl", _NS)
        if titel is None or not titel.text or url is None or not url.text:
            continue
        html_url = None
        for item in rec.iter(_GZD_TAG.replace("gzd", "itemUrl")):
            if item.get("manifestation") == "html" and item.text:
                html_url = item.text
        records.append(
            {
                "titel": titel.text,
                "datum": datum.text if datum is not None and datum.text else "",
                "url": url.text,
                "html_url": html_url,
            }
        )
    return records


def _laad_cache(pad: Path) -> dict:
    try:
        return json.loads(pad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _schrijf_cache(pad: Path, cache: dict) -> None:
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def haal_recente_vergunningen(
    cache_path: Path, steden, vandaag: date | None = None
) -> list[Vergunning]:
    """Haalt de recente 'Vergunning kamerverhuur <adres>'-bekendmakingen op voor de
    gevraagde steden en geocodeert elk adres. Geocoding-resultaten worden in
    cache_path bewaard (per publicatie-id), zodat een adres maar één keer bij PDOK
    wordt opgezocht en volgende runs snel zijn. Publicaties zonder bruikbaar adres
    (beleidsregels e.d.) worden overgeslagen; een adres dat niet geocodeert krijgt
    lat/lon None (en valt daarmee bij de afstandscheck af, geen vals alarm)."""
    vandaag = vandaag or date.today()
    cutoff = vandaag - timedelta(days=TERUGKIJK_DAGEN)
    cache = _laad_cache(cache_path)

    vergunningen: list[Vergunning] = []
    for stad in steden:
        cfg = _STAD_CONFIG.get(stad)
        if cfg is None:
            continue

        rauw: dict[str, dict] = {}
        for term in _ZOEKTERMEN:
            try:
                for rec in _haal_sru(term, cfg["creator"], cutoff):
                    pid = _pub_id(rec["url"])
                    if pid:
                        rauw.setdefault(pid, rec)
            except Exception as exc:  # noqa: BLE001 - nooit de scan laten crashen op KOOP-storing
                logger.warning("Kon bekendmakingen niet ophalen (%s, '%s'): %s", stad, term, exc)

        for pid, rec in rauw.items():
            adres = _adres_uit_titel(rec["titel"])
            if adres is None:
                continue

            cached = cache.get(pid)
            if cached is not None:
                lat, lon = cached.get("lat"), cached.get("lon")
                personen = cached.get("aantal_personen")
            else:
                lat = lon = None
                personen = None
                try:
                    geo = geocode_vrij(adres, cfg["woonplaats"])
                    lat, lon = geo.lat, geo.lon
                except GeocodeError as exc:
                    logger.info("Adres '%s' (%s) niet gevonden bij PDOK: %s", adres, pid, exc)
                except Exception as exc:  # noqa: BLE001 - PDOK-storing mag de scan niet stoppen
                    logger.warning("Geocoderen van '%s' (%s) mislukt: %s", adres, pid, exc)
                cache[pid] = {
                    "titel": rec["titel"],
                    "datum": rec["datum"],
                    "url": rec["url"],
                    "html_url": rec.get("html_url"),
                    "adres": adres,
                    "stad": stad,
                    "lat": lat,
                    "lon": lon,
                    "aantal_personen": None,
                }

            vergunningen.append(
                Vergunning(
                    pid, rec["titel"], rec["datum"], rec["url"], adres, stad, lat, lon,
                    html_url=rec.get("html_url") or (cached or {}).get("html_url"),
                    aantal_personen=personen,
                )
            )

    _schrijf_cache(cache_path, cache)
    return vergunningen


def _resolve_aantal_personen(verg: Vergunning, cache: dict) -> int | None:
    """Haalt (indien nog niet bekend) het aantal kamerbewoners uit de body van de
    bekendmaking - alleen aangeroepen voor vergunningen die al binnen 50 m van een
    favoriet blijken te liggen, dus zelden. Resultaat wordt in de cache bewaard.
    Hergebruikt de body-parser van de vergunningen-index (lokale import om een
    circulaire import te vermijden)."""
    if verg.aantal_personen is not None:
        return verg.aantal_personen
    if not verg.html_url:
        return None
    from . import vergunningenindex  # lokale import: vergunningenindex importeert bekendmakingen

    try:
        html = requests.get(verg.html_url, timeout=30).text
    except requests.exceptions.RequestException as exc:
        logger.info("Body ophalen mislukt voor personen-check (%s): %s", verg.publicatie_id, exc)
        return None
    velden = vergunningenindex.parse_body(html) or {}
    personen = velden.get("aantal_personen")
    if personen is not None and verg.publicatie_id in cache:
        cache[verg.publicatie_id]["aantal_personen"] = personen
    verg.aantal_personen = personen
    return personen


def afstand_meter(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Hemelsbrede afstand in meters (haversine) - ruim nauwkeurig genoeg voor een
    50 m-check op stadsschaal."""
    straal = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * straal * math.asin(math.sqrt(a))


def controleer_favorieten(state, cache_path: Path, vandaag: date | None = None):
    """Checkt voor elke favoriete woning of er een nieuwe kamerverhuurvergunning
    binnen 50 m is afgegeven, voegt gevonden waarschuwingen toe aan de woning en
    slaat de state op. Geeft een lijst (woning, nieuwe_waarschuwingen) terug van
    alleen de panden met deze run nieuw gevonden treffers - zodat pipeline.run
    daar precies één mail over kan sturen. Panden waarvan een treffer al eerder is
    gemeld (zelfde publicatie-id) leveren niets nieuws op."""
    favorieten = [
        item for item in state.all() if item.favoriet and item.lat is not None and item.lon is not None
    ]
    if not favorieten:
        return []

    steden = {(fav.stad or "rotterdam") for fav in favorieten}
    vergunningen = [
        v
        for v in haal_recente_vergunningen(cache_path, steden, vandaag=vandaag)
        if v.lat is not None and v.lon is not None
    ]
    if not vergunningen:
        return []

    # Cache (opnieuw) laden zodat we het achterhaalde aantal personen kunnen bewaren.
    cache = _laad_cache(cache_path)

    nieuw_per_pand = []
    for fav in favorieten:
        al_bekend = {w.get("publicatie_id") for w in fav.bekendmaking_waarschuwingen}
        nieuwe: list[dict] = []
        for verg in vergunningen:
            if verg.publicatie_id in al_bekend:
                continue
            afstand = afstand_meter(fav.lat, fav.lon, verg.lat, verg.lon)
            if afstand > STRAAL_METER:
                continue
            # Alleen 4+-vergunningen leggen een 50 m-afstandseis op (zie
            # MIN_KAMERBEWONERS_VOOR_AFSTANDSEIS); een bekende 3-persoons overslaan.
            personen = _resolve_aantal_personen(verg, cache)
            if personen is not None and personen < MIN_KAMERBEWONERS_VOOR_AFSTANDSEIS:
                continue
            waarschuwing = {
                "publicatie_id": verg.publicatie_id,
                "titel": verg.titel,
                "datum": verg.datum,
                "url": verg.url,
                "adres": verg.adres,
                "afstand_m": round(afstand),
                "aantal_personen": personen,
            }
            fav.bekendmaking_waarschuwingen.append(waarschuwing)
            al_bekend.add(verg.publicatie_id)
            nieuwe.append(waarschuwing)

        if nieuwe:
            state.upsert(fav)
            nieuw_per_pand.append((fav, nieuwe))

    _schrijf_cache(cache_path, cache)
    if nieuw_per_pand:
        state.save()
    return nieuw_per_pand


def bouw_alert_mail(nieuw_per_pand) -> tuple[str, str, str]:
    """Bouwt (onderwerp, html, tekst) voor de waarschuwingsmail over nieuw
    gevonden kamerverhuurvergunningen binnen 50 m van favoriete panden."""
    aantal = sum(len(nieuwe) for _fav, nieuwe in nieuw_per_pand)
    onderwerp = (
        f"⚠ Nieuwe kamerverhuurvergunning binnen 50 m van je favoriet"
        + ("en" if len(nieuw_per_pand) > 1 else "")
        + f" ({aantal} nieuw)"
    )

    tekst_regels = [
        "Er zijn nieuwe kamerverhuurvergunningen afgegeven binnen 50 meter van een",
        "woning die je als favoriet hebt gemarkeerd op kansen.steenhub.nl.",
        "",
        "Let op: deze officiële bekendmakingen lopen vóór op de gemeentekaart, dus dit",
        "is een vroege waarschuwing dat de vergunningskansen (nulquotum/afstandseis)",
        "voor dit pand kunnen veranderen.",
        "",
    ]
    html_blokken = [
        "<p>Er zijn nieuwe <strong>kamerverhuurvergunningen</strong> afgegeven binnen "
        "50 meter van een woning die je als favoriet hebt gemarkeerd op "
        "kansen.steenhub.nl.</p>",
        "<p style='color:#5f6368'>Deze officiële bekendmakingen lopen vóór op de "
        "gemeentekaart - een vroege waarschuwing dat de vergunningskansen "
        "(nulquotum/afstandseis) voor dit pand kunnen veranderen.</p>",
    ]

    for fav, nieuwe in nieuw_per_pand:
        tekst_regels.append(f"FAVORIET: {fav.weergavenaam}")
        html_blokken.append(f"<h3 style='margin-bottom:4px'>{fav.weergavenaam}</h3><ul>")
        for w in nieuwe:
            datum = w.get("datum") or "onbekende datum"
            pers = w.get("aantal_personen")
            pers_txt = f"{pers} personen" if pers else "aantal personen onbekend"
            regel = f"  • {w['adres']} — {pers_txt} — {w['afstand_m']} m — {datum} — {w['url']}"
            tekst_regels.append(regel)
            html_blokken.append(
                f"<li><strong>{w['adres']}</strong> — {pers_txt} — {w['afstand_m']} m — {datum} — "
                f"<a href=\"{w['url']}\">bekijk bekendmaking</a></li>"
            )
        html_blokken.append("</ul>")
        tekst_regels.append("")

    html_body = "<html><body>" + "".join(html_blokken) + "</body></html>"
    return onderwerp, html_body, "\n".join(tekst_regels)
