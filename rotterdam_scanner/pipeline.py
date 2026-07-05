from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .bag import fetch_bag_oppervlakte
from .config import Config
from .funda_mail import FundaListing, fetch_recent_funda_mail_scan, fetch_verwijder_commandos
from .geocode import GeocodeError, geocode_by_postcode
from .gis import binnen_50m_van_kamerverhuurvergunning, in_nulquotum_gebied
from .opkoop import check_opkoopbescherming
from .state import ListingState, StateStore
from .woz import meest_recente_woz_waarde


@dataclass
class RunResult:
    nieuw_actief: list[ListingState] = field(default_factory=list)
    nieuw_afgevallen: list[ListingState] = field(default_factory=list)
    nieuw_onbekend_adres: list[ListingState] = field(default_factory=list)
    handmatig_verwijderd: list[ListingState] = field(default_factory=list)
    alle_actief: list[ListingState] = field(default_factory=list)
    fouten: list[str] = field(default_factory=list)


def _process_new_listing(listing: FundaListing, config: Config, today: date) -> ListingState:
    today_iso = today.isoformat()
    # Alleen de handmatige tekstdump-parser kan hier een echte "sinds wanneer"-datum
    # aanleveren (bijv. uit "Sinds 3 maanden"); anders is vandaag prima, dat is ook wat
    # er voor een echt nieuwe woning uit de dagelijkse e-mail-alert hoort te staan. Dit
    # is los van laatst_gezien (altijd vandaag) waar de 30-dagen-expiry op afgaat, dus
    # een oude datum hier leidt niet tot meteen verlopen.
    eerst_gezien_iso = (listing.eerst_gezien_override or today).isoformat()

    if not listing.adres_bekend:
        return ListingState(
            object_id=listing.object_id,
            url=listing.url,
            weergavenaam=listing.weergavenaam,
            eerst_gezien=eerst_gezien_iso,
            laatst_gezien=today_iso,
            status="onbekend_adres",
            afvalreden="Kon postcode/huisnummer niet uit de e-mailtekst herleiden.",
        )

    try:
        geo = geocode_by_postcode(listing.postcode, listing.huisnummer, listing.toevoeging)
    except GeocodeError as exc:
        return ListingState(
            object_id=listing.object_id,
            url=listing.url,
            weergavenaam=listing.weergavenaam,
            eerst_gezien=eerst_gezien_iso,
            laatst_gezien=today_iso,
            status="onbekend_adres",
            afvalreden=f"Geocoding mislukt: {exc}",
        )

    if in_nulquotum_gebied(geo.rd_x, geo.rd_y):
        return ListingState(
            object_id=listing.object_id,
            url=listing.url,
            weergavenaam=geo.weergavenaam,
            eerst_gezien=eerst_gezien_iso,
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
            eerst_gezien=eerst_gezien_iso,
            laatst_gezien=today_iso,
            status="afgevallen",
            straatnaam=geo.straatnaam,
            huisnummer=geo.huisnummer,
            wijknaam=geo.rotterdam_wijk,
            afvalreden="Ligt binnen 50 meter van een bestaande kamerverhuurvergunning.",
        )

    opkoop = check_opkoopbescherming(geo.rotterdam_wijk, config.opkoopbescherming_woz_grens)
    opmerking = None

    if opkoop.in_beschermde_wijk:
        try:
            woz = meest_recente_woz_waarde(geo.nummeraanduiding_id)
        except Exception as exc:  # noqa: BLE001 - nooit crashen op een databron-storing
            woz = None
            opmerking = f"WOZ-waarde kon niet automatisch opgehaald worden ({exc}); handmatig checken."
        else:
            if woz is None:
                opmerking = "Geen publieke WOZ-waarde gevonden voor dit adres; handmatig checken."
            else:
                opkoop = check_opkoopbescherming(
                    geo.rotterdam_wijk, config.opkoopbescherming_woz_grens, woz_waarde=woz.bedrag
                )

    if opkoop.valt_af:
        return ListingState(
            object_id=listing.object_id,
            url=listing.url,
            weergavenaam=geo.weergavenaam,
            eerst_gezien=eerst_gezien_iso,
            laatst_gezien=today_iso,
            status="afgevallen",
            straatnaam=geo.straatnaam,
            huisnummer=geo.huisnummer,
            wijknaam=geo.rotterdam_wijk,
            afvalreden=opkoop.toelichting,
        )

    try:
        bag_oppervlakte = fetch_bag_oppervlakte(geo.adresseerbaarobject_id)
    except Exception as exc:  # noqa: BLE001 - nooit crashen op een databron-storing
        bag_oppervlakte = None
        opmerking = (opmerking + " " if opmerking else "") + f"BAG-oppervlakte kon niet opgehaald worden ({exc})."

    return ListingState(
        object_id=listing.object_id,
        url=listing.url,
        weergavenaam=geo.weergavenaam,
        eerst_gezien=eerst_gezien_iso,
        laatst_gezien=today_iso,
        status="actief",
        straatnaam=geo.straatnaam,
        huisnummer=geo.huisnummer,
        wijknaam=geo.rotterdam_wijk,
        woz_check_nodig=opkoop.woz_check_nodig,
        woz_check_url=opkoop.woz_check_url,
        opmerking=opmerking,
        prijs=listing.prijs,
        bag_oppervlakte=bag_oppervlakte,
    )


def _sorteersleutel(item: ListingState) -> tuple[int, float]:
    prijs_per_m2 = item.prijs_per_m2
    if prijs_per_m2 is None:
        return (1, 0.0)
    return (0, prijs_per_m2)


_HANDMATIG_VERWIJDERD_REDEN = "Handmatig verwijderd via de verwijder-link in het rapport."


def _verwerk_listings(
    listings: list[FundaListing],
    te_verwijderen_ids: set[str],
    config: Config,
    today: date,
    state: StateStore,
    result: RunResult,
    forceer_herprocessen: bool = False,
) -> None:
    today_iso = today.isoformat()

    for existing in state.all():
        if existing.object_id in te_verwijderen_ids and existing.status == "actief":
            existing.status = "afgevallen"
            existing.afvalreden = _HANDMATIG_VERWIJDERD_REDEN
            existing.laatst_gezien = today_iso
            state.upsert(existing)
            result.handmatig_verwijderd.append(existing)

    for listing in listings:
        existing = state.get(listing.object_id)
        # Een handmatig verwijderde woning nooit opnieuw laten opduiken, ook niet bij
        # forceer_herprocessen (dat is bedoeld om verouderde check-uitkomsten te
        # corrigeren, niet om verwijder-verzoeken van de gebruiker ongedaan te maken).
        handmatig_verwijderd = existing is not None and existing.afvalreden == _HANDMATIG_VERWIJDERD_REDEN
        if existing is not None and (not forceer_herprocessen or handmatig_verwijderd):
            existing.laatst_gezien = today_iso
            existing.url = listing.url
            if listing.prijs is not None:
                existing.prijs = listing.prijs
            state.upsert(existing)
            continue

        try:
            processed = _process_new_listing(listing, config, today)
        except Exception as exc:  # noqa: BLE001
            result.fouten.append(f"Fout bij verwerken van {listing.url}: {exc}")
            continue

        if processed.object_id in te_verwijderen_ids and processed.status == "actief":
            processed.status = "afgevallen"
            processed.afvalreden = _HANDMATIG_VERWIJDERD_REDEN

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
        key=_sorteersleutel,
    )


def run(config: Config, today: date | None = None) -> RunResult:
    today = today or date.today()
    state = StateStore(config.state_path)
    result = RunResult()

    try:
        scan = fetch_recent_funda_mail_scan(config)
    except Exception as exc:  # noqa: BLE001 - we willen dit altijd rapporteren, nooit stil laten falen
        result.fouten.append(f"Kon Funda-alertmail niet uitlezen: {exc}")
        scan = None

    listings = scan.listings if scan else []
    if scan:
        result.fouten.extend(scan.waarschuwingen)

    try:
        te_verwijderen_ids = fetch_verwijder_commandos(config)
    except Exception as exc:  # noqa: BLE001
        result.fouten.append(f"Kon verwijder-commando's niet uitlezen: {exc}")
        te_verwijderen_ids = set()

    _verwerk_listings(listings, te_verwijderen_ids, config, today, state, result)
    return result


def run_handmatig(
    config: Config,
    listings: list[FundaListing],
    today: date | None = None,
    forceer_herprocessen: bool = False,
) -> RunResult:
    """Verwerkt een handmatig aangeleverde lijst adressen (zie handmatig_toevoegen.py)
    via dezelfde checks en dezelfde state.json als de dagelijkse run, zodat ze vanaf nu
    ook meelopen in toekomstige dagrapporten.

    forceer_herprocessen=True laat ook adressen die al in state.json staan opnieuw door
    alle checks lopen (behalve handmatig verwijderde), voor het geval een eerdere
    check-uitkomst gecorrigeerd moet worden (bijv. na een bugfix)."""
    today = today or date.today()
    state = StateStore(config.state_path)
    result = RunResult()
    _verwerk_listings(listings, set(), config, today, state, result, forceer_herprocessen=forceer_herprocessen)
    return result
