from __future__ import annotations

from dataclasses import dataclass

import requests

# De officiële, gratis WOZ-waardeloket-API van het Kadaster (dezelfde die
# wozwaardeloket.nl zelf gebruikt). WOZ-waarden van woningen zijn sinds de wijziging
# van de Wet WOZ (2022) openbare informatie; dit endpoint geeft ze terug op basis van
# het BAG-nummeraanduiding-ID (uit de PDOK-geocode), zonder API-key of kosten.
# Let op: dit is een niet-officieel gedocumenteerde endpoint (teruggevonden in de
# publieke website), geen ontwikelaars-API met stabiliteitsgarantie -- als hij ooit
# stopt met werken, valt de opkoopbescherming-check terug op de handmatige melding
# in het rapport (zie pipeline.py).
BASE_URL = "https://api.kadaster.nl/lvwoz/wozwaardeloket-api/v1"


class WozApiError(RuntimeError):
    """De WOZ-waardeloket-API kon niet bevraagd worden (storing, onverwachte respons)."""


@dataclass(frozen=True)
class WozWaarde:
    peildatum: str
    bedrag: int


def fetch_woz_waarden(nummeraanduiding_id: str) -> list[WozWaarde]:
    resp = requests.get(
        f"{BASE_URL}/wozwaarde/nummeraanduiding/{nummeraanduiding_id}",
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if resp.status_code == 404:
        # Geen publieke WOZ-waarde bekend voor dit adres (bijv. geen woonfunctie, of
        # nog geen vastgestelde waarde) -- geen fout, gewoon geen data.
        return []
    resp.raise_for_status()

    data = resp.json()
    waarden = [
        WozWaarde(peildatum=item["peildatum"], bedrag=item["vastgesteldeWaarde"])
        for item in data.get("wozWaarden", []) or []
    ]
    return sorted(waarden, key=lambda w: w.peildatum, reverse=True)


def meest_recente_woz_waarde(nummeraanduiding_id: str) -> WozWaarde | None:
    waarden = fetch_woz_waarden(nummeraanduiding_id)
    return waarden[0] if waarden else None
