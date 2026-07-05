from __future__ import annotations

from dataclasses import dataclass

import requests

# https://woz-api.nl — commerciële, legitieme WOZ-API (geen scraping, gewone API-key
# authenticatie). Zie README voor registratie. We bevragen op nummeraanduiding-ID
# (uit de PDOK-geocode) in plaats van een vrije-tekst-adres, dat is ondubbelzinnig.
BASE_URL = "https://woz-api.nl/Api"


class WozApiError(RuntimeError):
    """De WOZ-API kon niet bevraagd worden (verkeerde/ontbrekende key, of storing)."""


@dataclass(frozen=True)
class WozWaarde:
    peildatum: str
    bedrag: int


def fetch_woz_waarden(nummeraanduiding_id: str, api_key: str) -> list[WozWaarde]:
    resp = requests.get(
        f"{BASE_URL}/Nummeraanduiding/{nummeraanduiding_id}",
        headers={"X-Api-Key": api_key},
        timeout=15,
    )
    if resp.status_code == 401:
        raise WozApiError("WOZ-API-key is ongeldig of ontbreekt (WOZ_API_KEY in .env).")
    resp.raise_for_status()

    data = resp.json()
    waarden = [
        WozWaarde(peildatum=item["peildatum"], bedrag=item["vastgesteldeWaarde"])
        for item in data.get("woz", []) or []
    ]
    return sorted(waarden, key=lambda w: w.peildatum, reverse=True)


def meest_recente_woz_waarde(nummeraanduiding_id: str, api_key: str) -> WozWaarde | None:
    waarden = fetch_woz_waarden(nummeraanduiding_id, api_key)
    return waarden[0] if waarden else None
