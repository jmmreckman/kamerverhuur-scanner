from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache

import requests


def _get_met_retry(url: str, *, params: dict | None = None, timeout: int = 20, pogingen: int = 3):
    """GET met retries + backoff. De gemeente-ArcGIS geeft onder druk read-timeouts of
    resets; zonder retry sneuvelt een adres dan onnodig op een tijdelijke fout."""
    laatste = None
    for i in range(pogingen):
        if i:
            time.sleep(2 * i)
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as exc:
            laatste = exc
    raise laatste

# De gemeente Rotterdam publiceert de kaartlagen achter de "Kamerverhuur"-kaart
# (https://experience.arcgis.com/experience/90c482180dbd4ab7ac0040c746ed80f5) periodiek
# opnieuw onder een nieuwe datasetnaam (bijv. "Nulquotum_gebieden_20250902",
# "Update_Juni2026"). Daarom zoeken we de actuele laag-URLs elke run dynamisch op via
# de webmap achter die kaart, in plaats van een vaste URL te hardcoden die na verloop
# van tijd stuk gaat.
WEBMAP_ITEM_ID = "3758c358745d48e7b3ba673957c3350b"
WEBMAP_DATA_URL = f"https://www.arcgis.com/sharing/rest/content/items/{WEBMAP_ITEM_ID}/data"

NULQUOTUM_TITLE_HINT = "nulquotum"
KAMERVERHUUR_TITLE_HINT = "kamerverhuur"


class GisLayerNotFoundError(RuntimeError):
    """De verwachte kaartlaag kon niet gevonden worden in de Rotterdam webmap."""


@dataclass(frozen=True)
class LayerUrls:
    nulquotum_url: str
    kamerverhuurvergunning_url: str


@lru_cache(maxsize=1)
def resolve_layer_urls() -> LayerUrls:
    resp = _get_met_retry(WEBMAP_DATA_URL, params={"f": "json"}, timeout=20)
    layers = resp.json().get("operationalLayers", [])

    nulquotum_url = None
    kamerverhuur_url = None
    for layer in layers:
        title = layer.get("title", "").lower()
        if NULQUOTUM_TITLE_HINT in title:
            nulquotum_url = layer["url"]
        elif KAMERVERHUUR_TITLE_HINT in title:
            kamerverhuur_url = layer["url"]

    if not nulquotum_url or not kamerverhuur_url:
        raise GisLayerNotFoundError(
            "Kon de nulquotum- en/of kamerverhuurvergunning-laag niet vinden in de "
            "Rotterdam webmap. De gemeente heeft de kaart mogelijk herstructureerd."
        )
    return LayerUrls(nulquotum_url=nulquotum_url, kamerverhuurvergunning_url=kamerverhuur_url)


def _point_intersects(layer_url: str, rd_x: float, rd_y: float) -> bool:
    resp = _get_met_retry(
        f"{layer_url}/query",
        params={
            "geometry": f"{rd_x},{rd_y}",
            "geometryType": "esriGeometryPoint",
            "inSR": 28992,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "OBJECTID",
            "returnGeometry": "false",
            "f": "json",
        },
        timeout=20,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"ArcGIS-fout bij bevragen {layer_url}: {data['error']}")
    return len(data.get("features", [])) > 0


def in_nulquotum_gebied(rd_x: float, rd_y: float) -> bool:
    urls = resolve_layer_urls()
    return _point_intersects(urls.nulquotum_url, rd_x, rd_y)


def binnen_50m_van_kamerverhuurvergunning(rd_x: float, rd_y: float) -> bool:
    # De gepubliceerde laag bevat al de samengevoegde 50-meter-invloedsgebieden rond
    # elke verleende vergunning (dus al gebufferd door de gemeente zelf). Een simpele
    # intersect-test volstaat; een extra "distance"-buffer zou dit tot 100 meter
    # oprekken.
    urls = resolve_layer_urls()
    return _point_intersects(urls.kamerverhuurvergunning_url, rd_x, rd_y)
