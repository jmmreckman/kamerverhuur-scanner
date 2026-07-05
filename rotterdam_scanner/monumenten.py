from __future__ import annotations

import requests

# Rijksdienst voor het Cultureel Erfgoed (RCE): officiële, gratis kaartendata voor
# rijksmonumenten en rijksbeschermde stads-/dorpsgezichten (geen API-key nodig).
_RCE_WFS_URL = "https://services.rce.geovoorziening.nl/rce/wfs"
RIJKSMONUMENTENREGISTER_URL = "https://monumentenregister.cultureelerfgoed.nl/"

# Rijksmonument-puntlocaties zijn soms "globaal" (niet pixel-precies), vandaar een
# kleine zoekstraal in plaats van een exacte puntmatch. Levert bij zeer dicht op elkaar
# staande panden een enkele valse positief op -- daarom altijd als "mogelijk" tonen met
# een link naar het officiële register om zelf te bevestigen.
_ZOEKSTRAAL_METER = 20

# Geen officiële, bevraagbare (open data) bron van de gemeente Rotterdam zelf gevonden
# voor gemeentelijke monumenten -- monumentenregister.rotterdam.nl is een interactieve
# webapplicatie zonder open-data-koppeling. Dit is een door een derde op ArcGIS
# gepubliceerde kopie van een Rotterdamse monumentenlijst uit 2021: bruikbaar als
# indicatie, maar niet gegarandeerd actueel of volledig.
_GEMEENTELIJKE_MONUMENTEN_FEATURESERVER = (
    "https://services.arcgis.com/emS4w7iyWEQiulAb/arcgis/rest/services/monumentenRotterdam2021/FeatureServer/2"
)
ROTTERDAM_MONUMENTENREGISTER_URL = "https://monumentenregister.rotterdam.nl/"


def _check_rijksmonument(rd_x: float, rd_y: float) -> tuple[bool, str | None]:
    resp = requests.get(
        _RCE_WFS_URL,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": "rce:NationalListedMonumentPoints",
            "srsName": "EPSG:28992",
            "bbox": (
                f"{rd_x - _ZOEKSTRAAL_METER},{rd_y - _ZOEKSTRAAL_METER},"
                f"{rd_x + _ZOEKSTRAAL_METER},{rd_y + _ZOEKSTRAAL_METER},EPSG:28992"
            ),
            "outputFormat": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    features = resp.json().get("features", [])
    if not features:
        return False, None
    return True, features[0]["properties"].get("rijksmonumenturl")


def _check_beschermd_stadsgezicht(rd_x: float, rd_y: float) -> tuple[bool, str | None]:
    resp = requests.get(
        _RCE_WFS_URL,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": "rce:Townscapes",
            "srsName": "EPSG:28992",
            "CQL_FILTER": (
                f"INTERSECTS(the_geom, POINT({rd_x} {rd_y})) "
                "AND JURSTATUS='rijksbeschermd stads- of dorpsgezicht'"
            ),
            "outputFormat": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    features = resp.json().get("features", [])
    if not features:
        return False, None
    return True, features[0]["properties"].get("NAAM")


def _check_mogelijk_gemeentelijk_monument(rd_x: float, rd_y: float) -> tuple[bool, str | None]:
    resp = requests.get(
        f"{_GEMEENTELIJKE_MONUMENTEN_FEATURESERVER}/query",
        params={
            "geometry": f"{rd_x},{rd_y}",
            "geometryType": "esriGeometryPoint",
            "inSR": 28992,
            "distance": _ZOEKSTRAAL_METER,
            "units": "esriSRUnit_Meter",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "USER_Omschrijving",
            "returnGeometry": "false",
            "f": "json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    features = resp.json().get("features", [])
    if not features:
        return False, None
    return True, features[0]["attributes"].get("USER_Omschrijving")


def bepaal_huurprijsopslag_signalen(rd_x: float, rd_y: float, bouwjaar: int | None) -> list[str]:
    """Geeft leesbare signalen terug over mogelijke huurprijsopslagen (WWS) op basis van
    monumentstatus/bouwjaar. Puur informatief -- filtert niets uit de lijst, en waar de
    onderliggende data niet 100% zeker of actueel is staat dat expliciet in de tekst
    zodat de gebruiker het zelf kan verifiëren voordat hij erop rekent."""
    signalen: list[str] = []

    is_rijksmonument, rijksmonument_url = _check_rijksmonument(rd_x, rd_y)
    if is_rijksmonument:
        signalen.append(
            f"Mogelijk rijksmonument (35% huurprijsopslag) — verifieer: "
            f"{rijksmonument_url or RIJKSMONUMENTENREGISTER_URL}"
        )

    is_beschermd, gezicht_naam = _check_beschermd_stadsgezicht(rd_x, rd_y)
    if is_beschermd:
        bouwjaar_tekst = f"bouwjaar {bouwjaar}" if bouwjaar is not None else "bouwjaar onbekend"
        signalen.append(
            f"Ligt in rijksbeschermd stads-/dorpsgezicht '{gezicht_naam}' ({bouwjaar_tekst}) — 5% "
            "huurprijsopslag mogelijk als het pand van vóór 1965 is én geen andere monumentenopslag krijgt."
        )

    if bouwjaar is not None and bouwjaar >= 2024:
        signalen.append(
            f"Bouwjaar {bouwjaar} (na 1 juli 2024) — nieuwbouwopslag (10%) mogelijk van toepassing "
            "op reguliere (niet-monumentale) middenhuurwoningen."
        )

    is_mogelijk_gemeentelijk, omschrijving = _check_mogelijk_gemeentelijk_monument(rd_x, rd_y)
    if is_mogelijk_gemeentelijk:
        signalen.append(
            "Mogelijk gemeentelijk monument (15% huurprijsopslag)"
            + (f": {omschrijving.strip()}" if omschrijving else "")
            + f" — gebaseerd op een lijst uit 2021, verifieer op {ROTTERDAM_MONUMENTENREGISTER_URL}."
        )

    return signalen
