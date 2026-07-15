from __future__ import annotations

from dataclasses import dataclass

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

# WWS-huurprijsopslagpercentages, zie report.py voor de volledige toelichting per soort.
_OPSLAG_RIJKSMONUMENT = 0.35
_OPSLAG_BESCHERMD_STADSGEZICHT = 0.05
_OPSLAG_NIEUWBOUW = 0.10
_OPSLAG_GEMEENTELIJK_MONUMENT = 0.15

# Beschermd-stadsgezicht-opslag geldt alleen voor panden van vóór 1965 (WWS-regel) --
# dit werd voorheen alleen in de signaaltekst genoemd, niet echt gecontroleerd.
_STADSGEZICHT_BOUWJAAR_GRENS = 1965


@dataclass(frozen=True)
class HuurprijsopslagSignaal:
    percentage: float
    tekst: str


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


def bepaal_huurprijsopslag(rd_x: float, rd_y: float, bouwjaar: int | None) -> list[HuurprijsopslagSignaal]:
    """Geeft signalen terug over mogelijke huurprijsopslagen (WWS) op basis van
    monumentstatus/bouwjaar, elk met het bijbehorende percentage. Puur informatief qua
    filtering (filtert niets uit de lijst), maar het percentage wordt wel gebruikt in de
    investeringsberekening (zie investering.py) -- waar de onderliggende data niet 100%
    zeker of actueel is staat dat expliciet in de tekst zodat de gebruiker het zelf kan
    verifiëren voordat hij erop rekent."""
    signalen: list[HuurprijsopslagSignaal] = []

    is_rijksmonument, rijksmonument_url = _check_rijksmonument(rd_x, rd_y)
    if is_rijksmonument:
        signalen.append(
            HuurprijsopslagSignaal(
                percentage=_OPSLAG_RIJKSMONUMENT,
                tekst=(
                    f"Mogelijk rijksmonument (35% huurprijsopslag) — verifieer: "
                    f"{rijksmonument_url or RIJKSMONUMENTENREGISTER_URL}"
                ),
            )
        )

    is_beschermd, gezicht_naam = _check_beschermd_stadsgezicht(rd_x, rd_y)
    if is_beschermd and bouwjaar is not None and bouwjaar < _STADSGEZICHT_BOUWJAAR_GRENS:
        signalen.append(
            HuurprijsopslagSignaal(
                percentage=_OPSLAG_BESCHERMD_STADSGEZICHT,
                tekst=(
                    f"Ligt in rijksbeschermd stads-/dorpsgezicht '{gezicht_naam}' (bouwjaar {bouwjaar}) — 5% "
                    "huurprijsopslag, mits geen andere monumentenopslag van toepassing is."
                ),
            )
        )

    if bouwjaar is not None and bouwjaar >= 2024:
        signalen.append(
            HuurprijsopslagSignaal(
                percentage=_OPSLAG_NIEUWBOUW,
                tekst=(
                    f"Bouwjaar {bouwjaar} (na 1 juli 2024) — nieuwbouwopslag (10%) mogelijk van toepassing "
                    "op reguliere (niet-monumentale) middenhuurwoningen."
                ),
            )
        )

    is_mogelijk_gemeentelijk, omschrijving = _check_mogelijk_gemeentelijk_monument(rd_x, rd_y)
    if is_mogelijk_gemeentelijk:
        signalen.append(
            HuurprijsopslagSignaal(
                percentage=_OPSLAG_GEMEENTELIJK_MONUMENT,
                tekst=(
                    "Mogelijk gemeentelijk monument (15% huurprijsopslag)"
                    + (f": {omschrijving.strip()}" if omschrijving else "")
                    + f" — gebaseerd op een lijst uit 2021, verifieer op {ROTTERDAM_MONUMENTENREGISTER_URL}."
                ),
            )
        )

    return signalen


def hoogste_opslagpercentage(signalen: list[HuurprijsopslagSignaal]) -> float:
    """De monumentenopslagen zijn volgens de WWS-regels niet stapelbaar (je krijgt de
    hoogste toepasselijke, niet de som) -- vandaar het maximum i.p.v. optellen."""
    return max((s.percentage for s in signalen), default=0.0)
