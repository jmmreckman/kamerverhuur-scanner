from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)


# rotterdam.nl geeft op een kale request zonder browser-User-Agent een 429
# (bot-block), waardoor de landingspagina-detectie stil op de fallback terugviel.
# Een normale User-Agent lost dat op; ArcGIS-REST heeft er geen last van.
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}


def _get_met_retry(url: str, *, params: dict | None = None, timeout: int = 20, pogingen: int = 3):
    """GET met retries + backoff. De gemeente-ArcGIS geeft onder druk read-timeouts of
    resets; zonder retry sneuvelt een adres dan onnodig op een tijdelijke fout."""
    laatste = None
    for i in range(pogingen):
        if i:
            time.sleep(2 * i)
        try:
            resp = requests.get(url, params=params, timeout=timeout, headers=_HTTP_HEADERS)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as exc:
            laatste = exc
    raise laatste


# ---------------------------------------------------------------------------
# Welke webmap zit er achter de "Kamerverhuur"-kaart?
#
# De gemeente Rotterdam publiceert de kaartlagen (nulquotum + verleende
# kamerverhuurvergunningen) achter de knop "kaart Kamerverhuur" op
# https://www.rotterdam.nl/vergunning-kamerverhuur-aanvragen. Twee dingen kunnen
# na verloop van tijd wijzigen:
#   1. de *datasetnaam* van een laag binnen dezelfde webmap (bijv.
#      "Nulquotum_gebieden_20250902" -> "Update_Juni2026"). Dat vangen we al op
#      door de lagen per run op titel op te zoeken (zie resolve_layer_urls).
#   2. de *webmap/experience zelf*: de gemeente zet periodiek een compleet nieuwe
#      kaart-app achter de knop (nieuw item-id). De oude directe link blijft dan
#      werken maar wijst naar een bevroren, niet meer bijgewerkte webmap.
#
# Punt 2 is het insidieuze geval: geen foutmelding, wel stille veroudering. Daarom
# hardcoden we het webmap-id niet meer, maar leiden we het elke run af van de knop
# op de landingspagina (landingspagina -> experience-app -> onderliggende webmap).
# De hieronder bekende id blijft als *fallback* staan voor als die keten onderuit
# gaat, en we waarschuwen in het dagrapport zodra we op de fallback terugvallen of
# zodra de gemeente een nieuw id blijkt te gebruiken (zodat de fallback bijgewerkt
# kan worden).
# ---------------------------------------------------------------------------
LANDINGSPAGINA_URL = "https://www.rotterdam.nl/vergunning-kamerverhuur-aanvragen"

# Laatst bekende webmap achter de kaart (peildatum sept 2026). Alleen fallback.
FALLBACK_WEBMAP_ITEM_ID = "3758c358745d48e7b3ba673957c3350b"

# Handmatige noodknop voor de beheerder: zet deze env-var om de auto-detectie te
# overrulen (bijv. als de gemeente iets doet wat we (nog) niet automatisch snappen).
ENV_OVERRIDE = "KAMERVERHUUR_WEBMAP_ITEM_ID"

_ARCGIS_ITEM_DATA = "https://www.arcgis.com/sharing/rest/content/items/{id}/data"
_ARCGIS_ITEM_INFO = "https://www.arcgis.com/sharing/rest/content/items/{id}"

# Een ArcGIS item-id is 32 hex-tekens. Op de landingspagina komt het voor als
# experience.arcgis.com/experience/<id> of als ...webappviewer/index.html?id=<id>.
# In ruwe HTML/JS kan de slash geëscaped zijn (experience\/<id>), dus [\\/]+.
_ITEM_ID_RE = re.compile(r"(?:experience[\\/]+|[?&]id=)([0-9a-f]{32})", re.IGNORECASE)
_HEX32_RE = re.compile(r"[0-9a-f]{32}", re.IGNORECASE)

NULQUOTUM_TITLE_HINT = "nulquotum"
KAMERVERHUUR_TITLE_HINT = "kamerverhuur"


class GisLayerNotFoundError(RuntimeError):
    """De verwachte kaartlaag kon niet gevonden worden in de Rotterdam webmap."""


@dataclass(frozen=True)
class LayerUrls:
    nulquotum_url: str
    kamerverhuurvergunning_url: str


@dataclass(frozen=True)
class KaartbronStatus:
    """Waar de scanner de kamerverhuur-webmap déze keer vandaan haalde. Puur voor
    transparantie in het dagrapport, zodat een gemeentelijke migratie of een
    teruggeval op de fallback niet stilletjes gebeurt."""

    webmap_item_id: str
    bron: str  # "env" | "landingspagina" | "fallback"
    experience_id: str | None
    waarschuwingen: tuple[str, ...]


_LAATSTE_STATUS: KaartbronStatus | None = None


def kaartbron_status() -> KaartbronStatus | None:
    """De status van de laatst uitgevoerde webmap-resolutie (of None als er deze
    proces-run nog geen laag is opgezocht). Forceert géén netwerk-call."""
    return _LAATSTE_STATUS


def _item_type(item_id: str) -> str:
    info = _get_met_retry(_ARCGIS_ITEM_INFO.format(id=item_id), params={"f": "json"}, timeout=15).json()
    return (info.get("type") or "").strip()


def _webmap_ids_uit_appdata(data: dict) -> list[str]:
    """Haal de onderliggende webmap-item-id's uit de config van een kaart-app
    (Experience Builder of de klassieke Web AppViewer)."""
    ids: list[str] = []
    # Experience Builder: dataSources is een dict; een webmap-bron heeft type
    # WEB_MAP (of iets met MAP) en een itemId.
    ds = data.get("dataSources")
    if isinstance(ds, dict):
        for bron in ds.values():
            if isinstance(bron, dict) and bron.get("itemId") and "MAP" in str(bron.get("type", "")).upper():
                ids.append(bron["itemId"])
    # Klassieke Web AppViewer: {"map": {"itemId": "..."}}.
    kaart = data.get("map")
    if isinstance(kaart, dict) and kaart.get("itemId"):
        ids.append(kaart["itemId"])
    return list(dict.fromkeys(ids))


def _ontdek_webmap_item_ids() -> list[str]:
    """Leid de actuele webmap-item-id('s) af van de knop op de landingspagina.
    Volledig defensief: bij welke fout dan ook geven we een lege lijst terug, zodat
    de aanroeper netjes op de fallback kan terugvallen."""
    try:
        html = _get_met_retry(LANDINGSPAGINA_URL, timeout=20).text
        if not isinstance(html, str):
            return []
    except Exception as exc:  # noqa: BLE001 - nooit crashen op een externe storing
        logger.warning("Kon kamerverhuur-landingspagina niet ophalen: %s", exc)
        return []

    app_ids = list(dict.fromkeys(m.group(1).lower() for m in _ITEM_ID_RE.finditer(html)))
    if not app_ids:
        return []

    webmap_ids: list[str] = []
    for app_id in app_ids:
        try:
            soort = _item_type(app_id).lower()
        except Exception:  # noqa: BLE001
            soort = ""
        if soort == "web map":
            webmap_ids.append(app_id)
            continue
        # Het is (waarschijnlijk) een app: graaf de onderliggende webmap('s) op.
        try:
            data = _get_met_retry(_ARCGIS_ITEM_DATA.format(id=app_id), params={"f": "json"}, timeout=20).json()
        except Exception:  # noqa: BLE001
            continue
        kandidaten = _webmap_ids_uit_appdata(data)
        if not kandidaten:
            # Structuur niet herkend: begrensde terugval op alle hex-id's in de
            # config, elk geverifieerd als webmap (max 8, om ArcGIS niet te
            # bestoken).
            for cid in list(dict.fromkeys(_HEX32_RE.findall(json.dumps(data))))[:8]:
                cid = cid.lower()
                if cid == app_id:
                    continue
                try:
                    if _item_type(cid).lower() == "web map":
                        kandidaten.append(cid)
                except Exception:  # noqa: BLE001
                    continue
        webmap_ids.extend(k.lower() for k in kandidaten)

    return list(dict.fromkeys(webmap_ids))


def _layers_uit_webmap(webmap_item_id: str) -> LayerUrls | None:
    """Haal de nulquotum- en kamerverhuurvergunning-laag uit één webmap. None als
    (een van) beide niet aanwezig is."""
    resp = _get_met_retry(_ARCGIS_ITEM_DATA.format(id=webmap_item_id), params={"f": "json"}, timeout=20)
    layers = resp.json().get("operationalLayers", [])
    nulquotum_url = None
    kamerverhuur_url = None
    for layer in layers:
        title = layer.get("title", "").lower()
        if NULQUOTUM_TITLE_HINT in title:
            nulquotum_url = layer.get("url")
        elif KAMERVERHUUR_TITLE_HINT in title:
            kamerverhuur_url = layer.get("url")
    if not nulquotum_url or not kamerverhuur_url:
        return None
    return LayerUrls(nulquotum_url=nulquotum_url, kamerverhuurvergunning_url=kamerverhuur_url)


# De resolutie is duur (meerdere externe calls) dus we cachen 'm. Bij een kort
# draaiend proces (de dagelijkse scan) is dat effectief 1x per run. Bij het
# langdraaiende site-proces zou een puur permanente cache een gemeentelijke migratie
# echter pas na een herstart oppikken; daarom vervalt de cache na een paar uur zodat
# ook de site zichzelf geneest.
_CACHE_TTL_SECONDS = 6 * 3600
_laatste_resolutie_ts = 0.0


def resolve_layer_urls() -> LayerUrls:
    """Zoek de actuele nulquotum- en kamerverhuurvergunning-kaartlagen op.

    Volgorde: (1) handmatige env-override, (2) de webmap achter de knop op de
    officiële landingspagina, (3) de laatst bekende webmap als fallback. De eerste
    die daadwerkelijk beide lagen bevat wint. De keuze + eventuele waarschuwingen
    zijn opvraagbaar via kaartbron_status(). Resultaat wordt gecachet met een TTL."""
    global _laatste_resolutie_ts
    nu = time.time()
    if nu - _laatste_resolutie_ts > _CACHE_TTL_SECONDS:
        _resolve_layer_urls_cached.cache_clear()
        _laatste_resolutie_ts = nu
    return _resolve_layer_urls_cached()


@lru_cache(maxsize=1)
def _resolve_layer_urls_cached() -> LayerUrls:
    global _LAATSTE_STATUS

    override = os.environ.get(ENV_OVERRIDE, "").strip()
    experience_id = None

    # Kandidaat-id's in volgorde van voorkeur, met hun herkomst. Een handmatige
    # env-override schakelt de auto-detectie bewust uit (dan wil de beheerder juist
    # deze webmap, wat de landingspagina ook zegt).
    kandidaten: list[tuple[str, str]] = []
    if override:
        kandidaten.append((override, "env"))
    else:
        for wid in _ontdek_webmap_item_ids():
            kandidaten.append((wid, "landingspagina"))
    kandidaten.append((FALLBACK_WEBMAP_ITEM_ID, "fallback"))

    dynamisch_gevonden = any(bron == "landingspagina" for _, bron in kandidaten)

    geprobeerd: set[str] = set()
    for webmap_id, bron in kandidaten:
        if webmap_id in geprobeerd:
            continue
        geprobeerd.add(webmap_id)
        try:
            urls = _layers_uit_webmap(webmap_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Webmap %s (%s) kon niet gelezen worden: %s", webmap_id, bron, exc)
            urls = None
        if urls is None:
            continue

        waarschuwingen: list[str] = []
        if bron == "fallback" and not override:
            if dynamisch_gevonden:
                waarschuwingen.append(
                    "⚠️ De actuele kamerverhuur-kaart achter de knop op "
                    f"{LANDINGSPAGINA_URL} leverde geen bruikbare lagen op; de scanner "
                    f"gebruikte de laatst bekende webmap ({webmap_id}). Controleer of de "
                    "kaart nog klopt."
                )
            else:
                waarschuwingen.append(
                    f"⚠️ Kon de kamerverhuur-kaart niet via {LANDINGSPAGINA_URL} "
                    f"terugvinden; de scanner gebruikte de laatst bekende webmap "
                    f"({webmap_id}). Controleer handmatig of de directe link nog actueel is."
                )
        elif bron == "landingspagina" and webmap_id != FALLBACK_WEBMAP_ITEM_ID:
            waarschuwingen.append(
                "ℹ️ Rotterdam gebruikt inmiddels een nieuwe kamerverhuur-webmap "
                f"(id {webmap_id}); de scanner is automatisch meegegaan. Werk "
                "FALLBACK_WEBMAP_ITEM_ID in rotterdam_scanner/gis.py bij naar deze id "
                "om de fallback vers te houden."
            )

        _LAATSTE_STATUS = KaartbronStatus(
            webmap_item_id=webmap_id,
            bron=bron,
            experience_id=experience_id,
            waarschuwingen=tuple(waarschuwingen),
        )
        return urls

    _LAATSTE_STATUS = KaartbronStatus(
        webmap_item_id="",
        bron="geen",
        experience_id=experience_id,
        waarschuwingen=(
            "⚠️ Geen enkele kamerverhuur-webmap (landingspagina noch fallback) bevatte "
            "de nulquotum- en vergunningslaag. De gemeente heeft de kaart mogelijk "
            "hergestructureerd; de 50m/nulquotum-check kon niet draaien.",
        ),
    )
    raise GisLayerNotFoundError(
        "Kon de nulquotum- en/of kamerverhuurvergunning-laag niet vinden in de "
        "Rotterdam webmap (landingspagina noch fallback). De gemeente heeft de kaart "
        "mogelijk herstructureerd."
    )


# Zodat bestaande code en tests `resolve_layer_urls.cache_clear()` kunnen blijven
# aanroepen ondanks de TTL-wrapper eromheen.
resolve_layer_urls.cache_clear = _resolve_layer_urls_cached.cache_clear


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
