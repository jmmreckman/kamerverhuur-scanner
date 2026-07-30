from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import quote_plus

from .funda_mail import FundaListing
from .state import ListingState

# Verwacht formaat per regel: "POSTCODE HUISNUMMER[TOEVOEGING] [funda-link]", bijv.
# "3073KJ 47A" of "3078 CN 44 https://www.funda.nl/detail/koop/rotterdam/huis-.../123/".
# Postcode + huisnummer is ondubbelzinnig (precies één adres in Nederland) en dat is
# alles wat nodig is om de woning door dezelfde checks te halen als de dagelijkse run.
_REGEL_RE = re.compile(
    r"^(?P<postcode>\d{4}\s?[A-Za-z]{2})\s+(?P<huisnummer>\d+)-?(?P<toevoeging>[A-Za-z0-9]*)"
    r"(?:\s+(?P<url>\S+))?\s*$"
)

# Zelfde vorm als funda_mail._maak_object_id(): "POSTCODE-HUISNUMMERTOEVOEGING", bijv.
# "3073KJ-47A". Elk "afgevallen"-adres in state.json heeft altijd zo'n ID, want afvallen
# kan pas nadat het adres al succesvol geocodeerd is (zie pipeline._process_new_listing).
_OBJECT_ID_RE = re.compile(r"^(?P<postcode>\d{4}[A-Z]{2})-(?P<huisnummer>\d+)(?P<toevoeging>[A-Za-z0-9]*)$")


def listing_state_naar_funda_listing(item: ListingState) -> FundaListing | None:
    """Reconstrueert een opnieuw te scannen FundaListing uit een bestaande
    state.json-regel, voor herscan_afgevallen.py - geeft None als de object_id niet
    het verwachte postcode-huisnummer-formaat heeft (zou niet moeten voorkomen bij een
    "afgevallen"-adres, maar voorkomt een crash op onverwacht oude/handmatige state)."""
    match = _OBJECT_ID_RE.match(item.object_id)
    if not match:
        return None
    return FundaListing(
        object_id=item.object_id,
        url=item.url,
        straatnaam=item.straatnaam,
        huisnummer=match.group("huisnummer"),
        toevoeging=match.group("toevoeging"),
        postcode=match.group("postcode"),
        woonplaats="Rotterdam",
    )


def _fallback_zoeklink(*adresdelen: str) -> str:
    """Zoeklink voor als er geen echte funda-link bekend is (handmatige invoer zonder
    link erbij). Funda's eigen postcode-zoek-URL (?selected_area=["postcode"]) is
    ongedocumenteerd en blijkt in de praktijk vaak geen resultaten te geven; een
    zoekopdracht is robuuster en laat bovendien meteen zien als de woning niet meer
    op funda staat."""
    query = " ".join(deel for deel in adresdelen if deel) + " funda"
    return f"https://www.google.com/search?q={quote_plus(query)}"


class HandmatigeRegelError(ValueError):
    """Een regel uit het handmatige adressenbestand kon niet gelezen worden."""


def parse_regel(regel: str) -> FundaListing:
    schoon = regel.strip()
    match = _REGEL_RE.match(schoon)
    if not match:
        raise HandmatigeRegelError(
            f"kon niet gelezen worden: '{schoon}'. Verwacht: 'POSTCODE HUISNUMMER[TOEVOEGING] "
            "[funda-link]', bijv. '3073KJ 47A' of '3078CN 44 https://www.funda.nl/...'."
        )

    postcode = match.group("postcode").replace(" ", "").upper()
    huisnummer = match.group("huisnummer")
    toevoeging = (match.group("toevoeging") or "").upper()
    url = match.group("url") or _fallback_zoeklink(postcode, f"{huisnummer}{toevoeging}")

    return FundaListing(
        object_id=f"{postcode}-{huisnummer}{toevoeging}",
        url=url,
        straatnaam=None,
        huisnummer=huisnummer,
        toevoeging=toevoeging,
        postcode=postcode,
        woonplaats=None,
    )


# Straat-adresregel zonder postcode: "Straat Huisnummer[ Toevoeging], Plaats", bijv.
# "Wassenaarseweg 257, Den Haag" of "Weimarstraat 70 A, Den Haag". Bedoeld voor lijsten
# die alleen straat + plaats geven (geen postcode) - die geocoden we dan op adres
# i.p.v. op postcode (zie pipeline._process_new_listing). Vereist een komma + plaats,
# zodat een "POSTCODE HUISNUMMER"-regel hier nooit per ongeluk op matcht.
_ADRES_PLAATS_RE = re.compile(
    r"^(?P<straat>.+?)\s+(?P<huisnummer>\d+)(?:\s+(?P<toevoeging>[A-Za-z][A-Za-z0-9]*))?"
    r"\s*,\s*(?P<plaats>[A-Za-zÀ-ÿ.'\- ]+)$"
)


def parse_adres_regel(regel: str) -> FundaListing:
    schoon = regel.strip()
    # Optioneel achter het adres, met "|" gescheiden: de (Funda-)woonoppervlakte en/of
    # de vraagprijs, bijv. "Wassenaarseweg 257, Den Haag | 218 | 595000" (of met opmaak:
    # "| 218 m² | € 595.000"). Volgorde-onafhankelijk: een getal >= 10.000 is de prijs,
    # kleiner is de m². Zonder m² valt de scanner terug op de BAG-oppervlakte (die bij
    # grensgevallen iets lager kan zijn); zonder prijs blijven winst/inleg leeg. Met
    # beide erbij gedraagt de import zich hetzelfde als de dagelijkse mail-route.
    oppervlakte_advertentie = None
    prijs = None
    if "|" in schoon:
        delen = schoon.split("|")
        schoon = delen[0].strip()
        for veld in delen[1:]:
            cijfers = re.sub(r"[^\d]", "", veld)
            if not cijfers:
                continue
            waarde = int(cijfers)
            if waarde >= 10_000:
                prijs = waarde
            else:
                oppervlakte_advertentie = waarde

    match = _ADRES_PLAATS_RE.match(schoon)
    if not match:
        raise HandmatigeRegelError(
            f"kon niet gelezen worden: '{schoon}'. Verwacht: 'STRAAT HUISNUMMER[TOEVOEGING], "
            "PLAATS', bijv. 'Wassenaarseweg 257, Den Haag'."
        )
    straat = match.group("straat").strip()
    huisnummer = match.group("huisnummer")
    toevoeging = (match.group("toevoeging") or "").upper()
    plaats = match.group("plaats").strip()
    # Voorlopige object_id (adres-slug): de pipeline vervangt 'm na geocoding door de
    # definitieve POSTCODE-HUISNUMMER-vorm, zodat een via adres toegevoegde woning
    # samenvalt met dezelfde woning uit de mail-alert (geen dubbeling).
    object_id = f"adres:{straat.lower()} {huisnummer}{toevoeging.lower()}, {plaats.lower()}"
    return FundaListing(
        object_id=object_id,
        url=_fallback_zoeklink(straat, f"{huisnummer}{toevoeging}", plaats),
        straatnaam=straat,
        huisnummer=huisnummer,
        toevoeging=toevoeging,
        postcode=None,
        woonplaats=plaats,
        prijs=prijs,
        oppervlakte_advertentie=oppervlakte_advertentie,
    )


def parse_adres_regels(regels: list[str]) -> tuple[list[FundaListing], list[str]]:
    listings: dict[str, FundaListing] = {}
    fouten: list[str] = []
    for regelnummer, regel in enumerate(regels, start=1):
        schoon = regel.strip()
        if not schoon or schoon.startswith("#"):
            continue
        try:
            listing = parse_adres_regel(schoon)
        except HandmatigeRegelError as exc:
            fouten.append(f"Regel {regelnummer} {exc}")
            continue
        listings[listing.object_id] = listing
    return list(listings.values()), fouten


def parse_regels(regels: list[str]) -> tuple[list[FundaListing], list[str]]:
    listings: dict[str, FundaListing] = {}
    fouten: list[str] = []
    for regelnummer, regel in enumerate(regels, start=1):
        schoon = regel.strip()
        if not schoon or schoon.startswith("#"):
            continue
        try:
            listing = parse_regel(schoon)
        except HandmatigeRegelError as exc:
            fouten.append(f"Regel {regelnummer} {exc}")
            continue
        listings[listing.object_id] = listing
    return list(listings.values()), fouten


# Herkent een ruwe kopieer-plak van een funda-zoekresultatenpagina (adres, postcode +
# plaats, vraagprijs, oppervlaktes, kamers, energielabel, makelaar, badges als
# "Blikvanger"/"Nieuw", soms "Sinds X weken/maanden" of een exacte datum, allemaal op
# losse regels, met een wisselend aantal regels en lege regels ertussen per woning). We
# ankeren op de postcode-regel (heel herkenbaar: 4 cijfers + 2 letters + plaatsnaam) en
# pakken de regel erboven als adres; de rest van het blok (tot de eerstvolgende
# postcode-regel) doorzoeken we op prijs en "sinds wanneer".
_POSTCODE_PLAATS_RE = re.compile(
    # Funda voegt bij sommige plaatsnamen die in meerdere provincies voorkomen (bv.
    # "Rozenburg (ZH)") een provincie-afkorting tussen haakjes toe - optioneel
    # meematchen (en niet in "plaats" opnemen) voorkomt dat zo'n regel helemaal niet
    # herkend wordt.
    r"^(?P<postcode>\d{4}\s?[A-Z]{2})\s+(?P<plaats>[A-Za-zÀ-ÿ.'\- ]+)(?:\s*\([A-Za-z]{2,3}\))?$"
)
_ADRESREGEL_RE = re.compile(r"^(?P<straat>.+?)\s+(?P<huisnummer>\d+)(?:-(?P<toevoeging>[A-Za-z0-9]+))?$")
_DUMP_PRIJS_RE = re.compile(r"€\s?([\d]{1,3}(?:[.,]\d{3})*)")
# Funda toont bij een huis twee losse "X m²"-regels op de kaart: eerst de woonoppervlakte,
# daarna de perceeloppervlakte (bij een appartement meestal maar één regel: wonen, geen
# eigen perceel). We pakken bewust alleen de EERSTE match in het blok - de tweede zou de
# perceeloppervlakte als woonoppervlak laten doorgaan, wat de kamerberekening/investering
# flink zou vertekenen (een groot perceel bij een klein huis geeft dan té veel kamers).
_DUMP_OPPERVLAKTE_RE = re.compile(r"^(\d{1,4})\s*m²$")

_MAANDEN = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}  # fmt: skip
_WEEKDAGEN = "maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag"
_EXACTE_DATUM_RE = re.compile(
    rf"^(?:{_WEEKDAGEN})\s+(\d{{1,2}})\s+({'|'.join(_MAANDEN)})$", re.IGNORECASE
)
_SINDS_RE = re.compile(r"^Sinds\s+(\d+)\s+(dag|dagen|week|weken|maand|maanden)$", re.IGNORECASE)


def _bepaal_eerst_gezien(blok: list[str], vandaag: date) -> date | None:
    for regel in blok:
        exacte_match = _EXACTE_DATUM_RE.match(regel)
        if exacte_match:
            dag = int(exacte_match.group(1))
            maand = _MAANDEN[exacte_match.group(2).lower()]
            kandidaat = date(vandaag.year, maand, dag)
            if kandidaat > vandaag:
                kandidaat = date(vandaag.year - 1, maand, dag)
            return kandidaat

        sinds_match = _SINDS_RE.match(regel)
        if sinds_match:
            aantal = int(sinds_match.group(1))
            eenheid = sinds_match.group(2).lower()
            # "weken" begint niet met "week" (klinkerwisseling: week -> weken), dus op de
            # eerste letter checken (d/w/m zijn hier altijd onderscheidend).
            dagen_per_eenheid = 30 if eenheid.startswith("maand") else 7 if eenheid.startswith("w") else 1
            return vandaag - timedelta(days=aantal * dagen_per_eenheid)

    return None


def parse_funda_tekstdump(tekst: str, vandaag: date | None = None) -> tuple[list[FundaListing], list[str]]:
    """Parseert tekst die je krijgt door een funda-zoekresultatenpagina te selecteren
    en te kopiëren/plakken (bijv. in Kladblok). Geen scraping: jij hebt de pagina zelf
    bekeken en de tekst zelf gekopieerd, dit leest 'm alleen uit."""
    vandaag = vandaag or date.today()
    regels = [r.strip() for r in tekst.splitlines()]
    listings: dict[str, FundaListing] = {}
    fouten: list[str] = []

    for i, regel in enumerate(regels):
        postcode_match = _POSTCODE_PLAATS_RE.match(regel)
        if not postcode_match:
            continue

        adres_regel = next((regels[j] for j in range(i - 1, -1, -1) if regels[j]), None)
        adres_match = _ADRESREGEL_RE.match(adres_regel) if adres_regel else None
        if not adres_match:
            fouten.append(
                f"Regel {i + 1}: postcode gevonden ('{regel}') maar geen herkenbaar adres erboven "
                f"('{adres_regel}')."
            )
            continue

        postcode = postcode_match.group("postcode").replace(" ", "").upper()
        huisnummer = adres_match.group("huisnummer")
        toevoeging = (adres_match.group("toevoeging") or "").upper()

        einde_blok = next(
            (j for j in range(i + 1, len(regels)) if _POSTCODE_PLAATS_RE.match(regels[j])), len(regels)
        )
        blok = regels[i + 1 : einde_blok]

        prijs = None
        for regel_in_blok in blok:
            prijs_match = _DUMP_PRIJS_RE.search(regel_in_blok)
            if prijs_match:
                prijs = int(re.sub(r"[.,]", "", prijs_match.group(1)))
                break

        oppervlakte_advertentie = None
        for regel_in_blok in blok:
            opp_match = _DUMP_OPPERVLAKTE_RE.match(regel_in_blok)
            if opp_match:
                oppervlakte_advertentie = int(opp_match.group(1))
                break

        object_id = f"{postcode}-{huisnummer}{toevoeging}"
        straatnaam = adres_match.group("straat").strip()
        listings[object_id] = FundaListing(
            object_id=object_id,
            url=_fallback_zoeklink(
                straatnaam, f"{huisnummer}{toevoeging}", postcode, postcode_match.group("plaats").strip()
            ),
            straatnaam=straatnaam,
            huisnummer=huisnummer,
            toevoeging=toevoeging,
            postcode=postcode,
            woonplaats=postcode_match.group("plaats").strip(),
            prijs=prijs,
            oppervlakte_advertentie=oppervlakte_advertentie,
            eerst_gezien_override=_bepaal_eerst_gezien(blok, vandaag),
        )

    return list(listings.values()), fouten


def parse_bestand(tekst: str) -> tuple[list[FundaListing], list[str]]:
    """Herkent automatisch welk formaat het is: eerst geprobeerd als ruwe
    funda-kopieer-plak-tekstdump (met postcodes); levert dat niets op, dan als
    straat-adreslijst "STRAAT HUISNUMMER, PLAATS" (zonder postcode, geocodet op
    adres); en anders als het simpele "POSTCODE HUISNUMMER [funda-link]"-formaat."""
    listings, fouten = parse_funda_tekstdump(tekst)
    if listings:
        return listings, fouten
    listings, fouten = parse_adres_regels(tekst.splitlines())
    if listings:
        return listings, fouten
    return parse_regels(tekst.splitlines())
