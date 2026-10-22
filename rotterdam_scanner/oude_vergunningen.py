"""Eenmalige import van de officiele 'Verleende vergunning kamerverhuur'-laag
(ArcGIS, gemeente Rotterdam) naar een losstaande database met adressen.

De officiele laag is EEN geaggregeerde multipolygon met ~473 parcel-vormen en GEEN
attributen (bewust geanonimiseerd: je ziet de vormen, niet de adressen/datums). We
splitsen die in losse parcels, nemen per parcel het zwaartepunt en reverse-geocoden
dat naar een adres via PDOK. Het resultaat is een info-/zichtlaag ("hier is ooit een
kamerverhuurvergunning verleend"): aantal personen (3/4+) en besluitdatum zijn
ONBEKEND, dus NIET bruikbaar voor de harde 50m-uitsluiting - puur ter informatie.

Schrijft oude_vergunningen.json naast state.json (de data-map op de VPS), bewust NIET
in git (adres-data van derden). Ontdubbelt tegen de al bekende vergunningen uit de
bekendmakingen-index op afstand, zodat "Toon oude vergunningen" alleen de extra
(historische) locaties toevoegt.

Eenmalig draaien op de VPS:
    docker compose run --rm fundazoeker python -m rotterdam_scanner.oude_vergunningen
"""
from __future__ import annotations

import logging
import math
import time
from datetime import date
from pathlib import Path

import requests

from .config import Config
from .geocode import adressen_binnen_straal
from .jsonbestand import schrijf_json_atomisch

logger = logging.getLogger(__name__)

# De laag die de officiele kamerverhuur-experience toont ("Verleende vergunning
# kamerverhuur"). Via de webmap van die experience-app gevonden.
ARCGIS_LAAG = (
    "https://services.arcgis.com/zP1tGdLpGvt2qNJ6/arcgis/rest/services/"
    "Update_Sept2026/FeatureServer/84"
)
# Binnen deze afstand van een al bekende vergunning rekenen we het als dezelfde
# (overlap) en nemen we 'm niet apart op in de oude-vergunningenlaag.
_DEDUP_M = 20.0


def pad_voor(config: Config) -> Path:
    return Path(config.state_path).parent / "oude_vergunningen.json"


def _index_pad(config: Config) -> Path:
    return Path(config.state_path).parent / "vergunningen_index.json"


def _ring_zwaartepunt(ring: list) -> tuple[float, float]:
    """Zwaartepunt (shoelace) van een polygon-ring [[lon,lat],...]; valt terug op het
    gemiddelde van de hoekpunten bij een degenererende/te kleine ring."""
    n = len(ring)
    opp = cx = cy = 0.0
    for i in range(n - 1):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[i + 1][0], ring[i + 1][1]
        f = x0 * y1 - x1 * y0
        opp += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if abs(opp) < 1e-12:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    opp *= 0.5
    return cx / (6 * opp), cy / (6 * opp)


def haal_parcel_middelpunten() -> list[tuple[float, float]]:
    """Alle parcel-zwaartepunten als (lat, lon) uit de ArcGIS-laag (WGS84)."""
    resp = requests.get(
        f"{ARCGIS_LAAG}/query",
        params={"where": "1=1", "outFields": "OBJECTID", "returnGeometry": "true", "f": "geojson"},
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    punten: list[tuple[float, float]] = []
    for feature in data.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") != "MultiPolygon":
            continue
        for polygoon in geom.get("coordinates", []):
            if not polygoon or not polygoon[0]:
                continue
            lon, lat = _ring_zwaartepunt(polygoon[0])  # buitenring
            punten.append((lat, lon))
    return punten


def _afstand_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Ruwe equirectangular-afstand in meters (genoeg voor een <100m-dedup)."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon) * 6_371_000.0


def _bekende_coords(config: Config) -> list[tuple[float, float]]:
    """Coordinaten van de al bekende (bekendmakingen-)vergunningen, voor de dedup."""
    from .vergunningenindex import VergunningIndex

    try:
        index = VergunningIndex(_index_pad(config))
        return [
            (v["lat"], v["lon"])
            for v in index.bruikbare()
            if v.get("lat") is not None and v.get("lon") is not None
        ]
    except Exception as exc:  # noqa: BLE001 - ontbrekende index = gewoon geen dedup
        logger.warning("Kon bekende vergunningen niet laden voor dedup: %s", exc)
        return []


def importeer(config: Config, *, pauze_s: float = 0.15) -> dict:
    """Haalt de parcels op, reverse-geocodeert, ontdubbelt en schrijft de database.
    Retourneert statistieken (voor de CLI-uitvoer)."""
    middelpunten = haal_parcel_middelpunten()
    bekend = _bekende_coords(config)

    records: list[dict] = []
    overlap = zonder_adres = 0
    for lat, lon in middelpunten:
        if any(_afstand_m(lat, lon, bl, bo) <= _DEDUP_M for bl, bo in bekend):
            overlap += 1
            continue
        adres = None
        try:
            nabij = adressen_binnen_straal(lat, lon, straal_m=35.0, max_adressen=1)
            if nabij:
                adres = nabij[0].weergavenaam
        except Exception as exc:  # noqa: BLE001 - nooit de hele import laten vallen
            logger.warning("reverse-geocode mislukt (%s, %s): %s", lat, lon, exc)
        if not adres:
            zonder_adres += 1
        records.append({
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "adres": adres,
            "bron": "arcgis_rotterdam",
        })
        time.sleep(pauze_s)

    schrijf_json_atomisch(pad_voor(config), {
        "bijgewerkt": date.today().isoformat(),
        "aantal": len(records),
        "overlap_met_bekend": overlap,
        "vergunningen": records,
    })
    return {
        "parcels": len(middelpunten),
        "opgeslagen": len(records),
        "overlap_met_bekend": overlap,
        "zonder_adres": zonder_adres,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from .config import load_config

    stats = importeer(load_config())
    print("Oude vergunningen geimporteerd:", stats)


if __name__ == "__main__":
    main()
