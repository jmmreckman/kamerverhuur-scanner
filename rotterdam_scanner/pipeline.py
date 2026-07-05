from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .config import Config
from .funda_mail import FundaListing, fetch_recent_funda_listings
from .geocode import GeocodeError, geocode_address
from .gis import binnen_50m_van_kamerverhuurvergunning, in_nulquotum_gebied
from .opkoop import check_opkoopbescherming
from .state import ListingState, StateStore
from .woz import meest_recente_woz_waarde


@dataclass
class RunResult:
    nieuw_actief: list[ListingState] = field(default_factory=list)
    nieuw_afgevallen: list[ListingState] = field(default_factory=list)
    nieuw_onbekend_adres: list[ListingState] = field(default_factory=list)
    alle_actief: list[ListingState] = field(default_factory=list)
    fouten: list[str] = field(default_factory=list)


def _process_new_listing(listing: FundaListing, config: Config, today: date) -> ListingState:
    today_iso = today.isoformat()

    if not listing.adres_bekend:
        return ListingState(
            object_id=listing.object_id,
            url=listing.url,
            weergavenaam=listing.url,
            eerst_gezien=today_iso,
            laatst_gezien=today_iso,
            status="onbekend_adres",
            afvalreden="Kon adres niet uit de funda-link herleiden.",
        )

    try:
        geo = geocode_address(listing.straatnaam, listing.huisnummer, listing.woonplaats)
    except GeocodeError as exc:
        return ListingState(
            object_id=listing.object_id,
            url=listing.url,
            weergavenaam=f"{listing.straatnaam} {listing.huisnummer}, {listing.woonplaats}",
            eerst_gezien=today_iso,
            laatst_gezien=today_iso,
            status="onbekend_adres",
            afvalreden=f"Geocoding mislukt: {exc}",
        )

    if in_nulquotum_gebied(geo.rd_x, geo.rd_y):
        return ListingState(
            object_id=listing.object_id,
            url=listing.url,
            weergavenaam=geo.weergavenaam,
            eerst_gezien=today_iso,
            laatst_gezien=today_iso,
            status="afgevallen",
            straatnaam=geo.straatnaam,
            huisnummer=geo.huisnummer,
            wijknaam=geo.rotterdam_wijk,
            afvalreden="Ligt in een nul-quotumgebied voor kamerverhuur.",
        )

    if binnen_50m_van_kamerverhuurvergunning(geo.rd_x, geo.rd_y):
        return ListingState(
            object_id=listing.object_id,
            url=listing.url,
            weergavenaam=geo.weergavenaam,
            eerst_gezien=today_iso,
            laatst_gezien=today_iso,
            status="afgevallen",
            straatnaam=geo.straatnaam,
            huisnummer=geo.huisnummer,
            wijknaam=geo.rotterdam_wijk,
            afvalreden="Ligt binnen 50 meter van een bestaande kamerverhuurvergunning.",
        )

    opkoop = check_opkoopbescherming(geo.rotterdam_wijk, config.opkoopbescherming_woz_grens)
    opmerking = None

    if opkoop.in_beschermde_wijk and config.woz_api_key:
        try:
            woz = meest_recente_woz_waarde(geo.nummeraanduiding_id, config.woz_api_key)
        except Exception as exc:  # noqa: BLE001 - nooit crashen op een databron-storing
            woz = None
            opmerking = f"WOZ-waarde kon niet automatisch opgehaald worden ({exc}); handmatig checken."
        else:
            if woz is None:
                opmerking = "WOZ-API had geen waarde voor dit adres; handmatig checken."
            else:
                opkoop = check_opkoopbescherming(
                    geo.rotterdam_wijk, config.opkoopbescherming_woz_grens, woz_waarde=woz.bedrag
                )

    if opkoop.valt_af:
        return ListingState(
            object_id=listing.object_id,
            url=listing.url,
            weergavenaam=geo.weergavenaam,
            eerst_gezien=today_iso,
            laatst_gezien=today_iso,
            status="afgevallen",
            straatnaam=geo.straatnaam,
            huisnummer=geo.huisnummer,
            wijknaam=geo.rotterdam_wijk,
            afvalreden=opkoop.toelichting,
        )

    return ListingState(
        object_id=listing.object_id,
        url=listing.url,
        weergavenaam=geo.weergavenaam,
        eerst_gezien=today_iso,
        laatst_gezien=today_iso,
        status="actief",
        straatnaam=geo.straatnaam,
        huisnummer=geo.huisnummer,
        wijknaam=geo.rotterdam_wijk,
        woz_check_nodig=opkoop.woz_check_nodig,
        woz_check_url=opkoop.woz_check_url,
        opmerking=opmerking,
    )


def run(config: Config, today: date | None = None) -> RunResult:
    today = today or date.today()
    state = StateStore(config.state_path)
    result = RunResult()

    try:
        listings = fetch_recent_funda_listings(config)
    except Exception as exc:  # noqa: BLE001 - we willen dit altijd rapporteren, nooit stil laten falen
        result.fouten.append(f"Kon Funda-alertmail niet uitlezen: {exc}")
        listings = []

    for listing in listings:
        existing = state.get(listing.object_id)
        if existing is not None:
            existing.laatst_gezien = today.isoformat()
            state.upsert(existing)
            continue

        try:
            processed = _process_new_listing(listing, config, today)
        except Exception as exc:  # noqa: BLE001
            result.fouten.append(f"Fout bij verwerken van {listing.url}: {exc}")
            continue

        state.upsert(processed)
        if processed.status == "actief":
            result.nieuw_actief.append(processed)
        elif processed.status == "afgevallen":
            result.nieuw_afgevallen.append(processed)
        else:
            result.nieuw_onbekend_adres.append(processed)

    state.prune_expired(config.listing_expiry_days, today=today)
    state.save()

    result.alle_actief = sorted(
        (item for item in state.all() if item.status == "actief"),
        key=lambda item: item.eerst_gezien,
        reverse=True,
    )
    return result
