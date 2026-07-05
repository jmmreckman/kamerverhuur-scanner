from __future__ import annotations

import requests

# Publieke PDOK BAG-WFS, geen API-key nodig — dit is de landelijke basisregistratie
# adressen en gebouwen, dus de "officiele" oppervlakte i.p.v. de (vaak afwijkende)
# advertentietekst op funda.
BAG_WFS_URL = "https://service.pdok.nl/lv/bag/wfs/v2_0"


def fetch_bag_oppervlakte(adresseerbaarobject_id: str) -> int | None:
    if not adresseerbaarobject_id:
        return None

    filter_xml = (
        "<Filter><PropertyIsEqualTo><PropertyName>identificatie</PropertyName>"
        f"<Literal>{adresseerbaarobject_id}</Literal></PropertyIsEqualTo></Filter>"
    )
    resp = requests.get(
        BAG_WFS_URL,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": "bag:verblijfsobject",
            "outputFormat": "json",
            "filter": filter_xml,
        },
        timeout=15,
    )
    resp.raise_for_status()
    features = resp.json().get("features", [])
    if not features:
        return None
    return features[0]["properties"].get("oppervlakte")
