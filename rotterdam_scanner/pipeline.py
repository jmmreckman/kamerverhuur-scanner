from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .bag import fetch_bag_gegevens
from .beschikbaarheid import controleer_beschikbaar
from .config import Config
from .funda_mail import FundaListing, fetch_recent_funda_mail_scan, fetch_verwijder_commandos
from .geocode import GeocodeError, geocode_by_postcode
from .gis import binnen_50m_van_kamerverhuurvergunning, in_nulquotum_gebied
from .investering import aantal_kamers_mogelijk as bereken_aantal_kamers_mogelijk
from .investering import bereken as bereken_investering
from .investering import bereken_met_aantal_kamers as bereken_investering_met_aantal_kamers
from .monumenten import bepaal_huurprijsopslag, hoogste_opslagpercentage
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
            lat=geo.lat,
            lon=geo.lon,
            afvalreden="Ligt in een nul-quotumgebied voor kamerverhuur.",
        )

    # Het aantal kamers moet al bekend zijn vóór de 50-meter-check hieronder: bij
    # kleinschalige kamerverhuur (t/m 3 kamers) geldt de 50-meter-afstandsregel niet
    # (bron: gemeentelijk kamerverhuurbeleid) - vandaar dat de BAG-oppervlakte hier
    # eerder wordt opgehaald dan voorheen (was verderop, na alle geo-checks).
    opmerking = None
    try:
        bag = fetch_bag_gegevens(geo.adresseerbaarobject_id)
    except Exception as exc:  # noqa: BLE001 - nooit crashen op een databron-storing
        bag = None
        opmerking = f"BAG-gegevens konden niet opgehaald worden ({exc})."
    bag_oppervlakte = bag.oppervlakte if bag else None
    bouwjaar = bag.bouwjaar if bag else None
    # Advertentie-m2 is betrouwbaarder dan BAG-m2 (die soms een veel hogere
    # waarde geeft) en is daarom leidend; BAG-m2 is alleen fallback/ter info,
    # zie ListingState.primaire_oppervlakte.
    primaire_oppervlakte = listing.oppervlakte_advertentie or bag_oppervlakte
    aantal_kamers = bereken_aantal_kamers_mogelijk(primaire_oppervlakte) if primaire_oppervlakte else None

    # Onbekend aantal kamers (bv. BAG-storing) telt NIET als vrijgesteld - dan blijft de
    # 50-meter-regel voor de zekerheid gewoon gelden.
    vrijgesteld_van_50m_regel = aantal_kamers is not None and aantal_kamers <= 3
    if vrijgesteld_van_50m_regel:
        opmerking = (opmerking + " " if opmerking else "") + (
            f"50-meter-regel niet van toepassing: bij {aantal_kamers} kamer(s) "
            "(kleinschalige kamerverhuur, t/m 3) geldt die uitzondering."
        )
    elif binnen_50m_van_kamerverhuurvergunning(geo.rd_x, geo.rd_y):
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
            lat=geo.lat,
            lon=geo.lon,
            afvalreden="Ligt binnen 50 meter van een bestaande kamerverhuurvergunning.",
        )

    opkoop = check_opkoopbescherming(geo.rotterdam_wijk, config.opkoopbescherming_woz_grens)

    if opkoop.in_beschermde_wijk:
        try:
            woz = meest_recente_woz_waarde(geo.nummeraanduiding_id)
        except Exception as exc:  # noqa: BLE001 - nooit crashen op een databron-storing
            woz = None
            opmerking = (opmerking + " " if opmerking else "") + (
                f"WOZ-waarde kon niet automatisch opgehaald worden ({exc}); handmatig checken."
            )
        else:
            if woz is None:
                opmerking = (opmerking + " " if opmerking else "") + (
                    "Geen publieke WOZ-waarde gevonden voor dit adres; handmatig checken."
                )
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
            lat=geo.lat,
            lon=geo.lon,
            afvalreden=opkoop.toelichting,
        )

    opslag_percentage = 0.0
    try:
        opslag_signalen = bepaal_huurprijsopslag(geo.rd_x, geo.rd_y, bouwjaar)
        opslag_percentage = hoogste_opslagpercentage(opslag_signalen)
    except Exception as exc:  # noqa: BLE001 - nooit crashen op een databron-storing
        opslag_signalen = []
        opmerking = (
            opmerking + " " if opmerking else ""
        ) + f"Monumenten-/opslagcheck kon niet uitgevoerd worden ({exc})."

    winst_pm_pp = None
    eigen_inleg_pp = None
    if primaire_oppervlakte and listing.prijs:
        investering = bereken_investering(primaire_oppervlakte, listing.prijs, opslag_percentage)
        if investering is not None:
            winst_pm_pp = investering.winst_pm_pp
            eigen_inleg_pp = investering.eigen_inleg_na_ophoging_pp

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
        lat=geo.lat,
        lon=geo.lon,
        woz_check_nodig=opkoop.woz_check_nodig,
        woz_check_url=opkoop.woz_check_url,
        opmerking=opmerking,
        prijs=listing.prijs,
        bag_oppervlakte=bag_oppervlakte,
        oppervlakte_advertentie=listing.oppervlakte_advertentie,
        huurprijsopslag_signalen=[s.tekst for s in opslag_signalen],
        opslag_percentage=opslag_percentage,
        aantal_kamers_mogelijk=aantal_kamers,
        winst_pm_pp=winst_pm_pp,
        eigen_inleg_pp=eigen_inleg_pp,
    )


def _sorteersleutel(item: ListingState) -> tuple[int, float]:
    # Laagste eigen inleg per persoon eerst (beste kansen bovenaan) - ontbrekende
    # waarden (bv. geen BAG-oppervlakte of vraagprijs bekend) onderaan.
    if item.eigen_inleg_pp is None:
        return (1, 0.0)
    return (0, item.eigen_inleg_pp)


def _backvul_investeringscijfers(state: StateStore) -> None:
    """Woningen die al in state.json stonden vóórdat de investeringsberekening
    bestond (of vóór een latere aanpassing eraan) missen winst_pm_pp/eigen_inleg_pp/
    aantal_kamers_mogelijk. Ze worden alleen bijgewerkt via de normale
    (nieuw-adres-)pipeline, dus zonder dit zouden ze die velden nooit met
    terugwerkende kracht krijgen. Kost geen nieuwe geocode-/BAG-/monumenten-
    aanroepen: bag_oppervlakte, oppervlakte_advertentie, prijs en
    opslag_percentage staan al in de state.

    Herberekent aantal_kamers_mogelijk/winst_pm_pp/eigen_inleg_pp ook opnieuw
    (niet alleen als ze nog ontbreken) op basis van primaire_oppervlakte, zodat
    woningen die eerder op de (soms te hoge) BAG-m2 berekend zijn automatisch
    het juiste kameraantal/investeringscijfer krijgen zodra dit run draait -
    zie ListingState.primaire_oppervlakte. Woningen met een handmatig aangepast
    aantal kamers (aantal_kamers_handmatig) worden met rust gelaten voor het
    kameraantal zelf - de investeringscijfers blijven wel meerekenen op basis van
    dat handmatige aantal (bv. als de vraagprijs nog wijzigt)."""
    for item in state.all():
        oppervlakte = item.primaire_oppervlakte
        if item.status != "actief" or not oppervlakte:
            continue

        if not item.aantal_kamers_handmatig:
            nieuw_aantal_kamers = bereken_aantal_kamers_mogelijk(oppervlakte)
            if item.aantal_kamers_mogelijk != nieuw_aantal_kamers:
                item.aantal_kamers_mogelijk = nieuw_aantal_kamers
                state.upsert(item)

        if not item.prijs or not item.aantal_kamers_mogelijk:
            continue
        investering = bereken_investering_met_aantal_kamers(
            item.aantal_kamers_mogelijk, item.prijs, item.opslag_percentage, m2=oppervlakte
        )
        if investering is None:
            continue
        if (
            item.winst_pm_pp != investering.winst_pm_pp
            or item.eigen_inleg_pp != investering.eigen_inleg_na_ophoging_pp
        ):
            item.winst_pm_pp = investering.winst_pm_pp
            item.eigen_inleg_pp = investering.eigen_inleg_na_ophoging_pp
            state.upsert(item)


def _backvul_coordinaten(state: StateStore) -> None:
    """Woningen die al in state.json stonden vóórdat coördinaten (lat/lon)
    werden opgeslagen missen die nog - zonder dit zouden ze nooit op de kaart
    (kansen.steenhub.nl) verschijnen, ook al staan ze gewoon nog "actief". De
    'bestaat al'-tak in _verwerk_listings hieronder geocodeert bewust niet
    opnieuw (dat zou voor elke al bekende woning een extra PDOK-aanroep per
    run betekenen) - dit haalt het eenmalig en gericht in, alleen voor
    woningen waar het nog ontbreekt. Kost 1 PDOK-aanroep per ontbrekende
    woning; best-effort, net als de rest van dit bestand: een storing hier
    mag de rest van de run nooit laten mislukken.

    Postcode staat niet los opgeslagen op ListingState - object_id is altijd
    "POSTCODE-HUISNUMMER[TOEVOEGING]" (zie funda_mail._maak_object_id()),
    dus die wordt er hier weer uit gehaald i.p.v. een extra veld toe te
    voegen."""
    for item in state.all():
        if item.status != "actief" or item.lat is not None or not item.huisnummer:
            continue
        postcode = item.object_id.split("-", 1)[0]
        try:
            geo = geocode_by_postcode(postcode, item.huisnummer, "")
        except GeocodeError:
            continue
        item.lat = geo.lat
        item.lon = geo.lon
        state.upsert(item)


def _backvul_opkoopbescherming(state: StateStore, config: Config, today_iso: str, result: RunResult) -> None:
    """Woningen die als "actief" bleven staan met woz_check_nodig=True (de automatische
    WOZ-opvraging is bij de eerste verwerking mislukt, of gaf toen nog geen resultaat -
    bv. omdat de WOZ-waarde voor dat peiljaar nog niet gepubliceerd was) krijgen hier een
    herkansing: als de WOZ-waarde nu wel op te halen is, wordt de opkoopbescherming-check
    alsnog afgemaakt, precies zoals die op dag 1 had moeten verlopen als de opvraging toen
    al gelukt was. Zonder dit blijft zo'n woning voor altijd "actief" staan, ook als hij
    eigenlijk in een beschermde wijk met een te lage WOZ-waarde ligt.

    Kost 1 PDOK- + 1 WOZ-aanroep per woning die nog op handmatige controle staat;
    best-effort, een storing hier mag de rest van de run nooit laten mislukken."""
    for item in state.all():
        if item.status != "actief" or not item.woz_check_nodig or not item.huisnummer:
            continue
        postcode = item.object_id.split("-", 1)[0]
        try:
            geo = geocode_by_postcode(postcode, item.huisnummer, "")
            woz = meest_recente_woz_waarde(geo.nummeraanduiding_id)
        except Exception:  # noqa: BLE001 - nooit crashen op een databron-storing
            continue
        if woz is None:
            continue

        opkoop = check_opkoopbescherming(
            item.wijknaam or geo.rotterdam_wijk, config.opkoopbescherming_woz_grens, woz_waarde=woz.bedrag
        )
        item.woz_check_nodig = False
        item.woz_check_url = None
        # De opmerking van dag 1 legde uit waarom de WOZ-check toen nog niet lukte - nu
        # die alsnog gelukt is, klopt die tekst niet meer (alleen als het de enige
        # opmerking was; een gecombineerde opmerking met bv. een BAG-storing laten we
        # met rust, dat is nog steeds relevant).
        if item.opmerking in (
            "Geen publieke WOZ-waarde gevonden voor dit adres; handmatig checken.",
        ) or (item.opmerking or "").startswith("WOZ-waarde kon niet automatisch opgehaald worden"):
            item.opmerking = None
        if opkoop.valt_af:
            item.status = "afgevallen"
            item.afvalreden = opkoop.toelichting
            item.laatst_gezien = today_iso
            result.nieuw_afgevallen.append(item)
        state.upsert(item)


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
            existing.handmatig_verwijderd = True
            existing.laatst_gezien = today_iso
            state.upsert(existing)
            result.handmatig_verwijderd.append(existing)

    for listing in listings:
        existing = state.get(listing.object_id)
        # Een handmatig verwijderde woning nooit opnieuw laten opduiken, ook niet bij
        # forceer_herprocessen (dat is bedoeld om verouderde check-uitkomsten te
        # corrigeren, niet om verwijder-verzoeken van de gebruiker ongedaan te maken) -
        # ongeacht of dat via de mail-link of het kruisje op kansen.steenhub.nl ging.
        handmatig_verwijderd = existing is not None and existing.handmatig_verwijderd
        if existing is not None and (not forceer_herprocessen or handmatig_verwijderd):
            existing.laatst_gezien = today_iso
            existing.url = listing.url
            if listing.prijs is not None:
                existing.prijs = listing.prijs
            if listing.oppervlakte_advertentie is not None:
                existing.oppervlakte_advertentie = listing.oppervlakte_advertentie
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
            processed.handmatig_verwijderd = True

        state.upsert(processed)
        if processed.status == "actief":
            result.nieuw_actief.append(processed)
        elif processed.status == "afgevallen":
            result.nieuw_afgevallen.append(processed)
        else:
            result.nieuw_onbekend_adres.append(processed)

    _backvul_investeringscijfers(state)
    _backvul_coordinaten(state)
    _backvul_opkoopbescherming(state, config, today_iso, result)
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


def run_beschikbaarheidscheck(config: Config, today: date | None = None) -> RunResult:
    """Bezoekt voor elke "actief" woning gewoon de eigen (al bekende) Funda-URL
    rechtstreeks en checkt aan de paginatitel of hij nog "te koop" staat, of
    inmiddels "verkocht" - i.p.v. een betaalde scraper/zoek-actor (die bleek
    onbetrouwbaar, zie geschiedenis van dit bestand vóór deze functie). Puur
    best-effort: bij een netwerkfout, blokkade of onduidelijk resultaat wordt
    een woning met rust gelaten (nooit per ongeluk verwijderd op basis van een
    twijfelachtig signaal) - alleen een expliciet "verkocht"-signaal in de
    paginatitel zet 'm op "afgevallen". Woningen die nergens meer op reageren
    (bv. écht van de site gehaald, 404) blijven ook gewoon staan tot de
    normale 30-dagen-expiry (state.prune_expired) ze opruimt - dat is bewust
    voorzichtiger dan hard verwijderen op een dubbelzinnig signaal."""
    today = today or date.today()
    today_iso = today.isoformat()
    state = StateStore(config.state_path)
    result = RunResult()

    for item in state.all():
        if item.status != "actief":
            continue
        beschikbaar = controleer_beschikbaar(item.url)
        if beschikbaar is None:
            continue
        item.laatst_gezien = today_iso
        if not beschikbaar:
            item.status = "afgevallen"
            item.afvalreden = "Niet meer 'te koop' op de eigen Funda-pagina - vermoedelijk verkocht."
            result.nieuw_afgevallen.append(item)
        state.upsert(item)

    state.prune_expired(config.listing_expiry_days, today=today)
    state.save()

    result.alle_actief = sorted(
        (item for item in state.all() if item.status == "actief"),
        key=_sorteersleutel,
    )
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
