from __future__ import annotations

import re
from datetime import date, timedelta

from .funda_mail import FundaListing

# Verwacht formaat per regel: "POSTCODE HUISNUMMER[TOEVOEGING] [funda-link]", bijv.
# "3073KJ 47A" of "3078 CN 44 https://www.funda.nl/detail/koop/rotterdam/huis-.../123/".
# Postcode + huisnummer is ondubbelzinnig (precies één adres in Nederland) en dat is
# alles wat nodig is om de woning door dezelfde checks te halen als de dagelijkse run.
_REGEL_RE = re.compile(
    r"^(?P<postcode>\d{4}\s?[A-Za-z]{2})\s+(?P<huisnummer>\d+)-?(?P<toevoeging>[A-Za-z0-9]*)"
    r"(?:\s+(?P<url>\S+))?\s*$"
)


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
    url = match.group("url") or f"https://www.funda.nl/zoeken/koop/?selected_area=%5B%22{postcode}%22%5D"

    return FundaListing(
        object_id=f"{postcode}-{huisnummer}{toevoeging}",
        url=url,
        straatnaam=None,
        huisnummer=huisnummer,
        toevoeging=toevoeging,
        postcode=postcode,
        woonplaats=None,
    )


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
_POSTCODE_PLAATS_RE = re.compile(r"^(?P<postcode>\d{4}\s?[A-Z]{2})\s+(?P<plaats>[A-Za-zÀ-ÿ.'\- ]+)$")
_ADRESREGEL_RE = re.compile(r"^(?P<straat>.+?)\s+(?P<huisnummer>\d+)(?:-(?P<toevoeging>[A-Za-z0-9]+))?$")
_DUMP_PRIJS_RE = re.compile(r"€\s?([\d]{1,3}(?:[.,]\d{3})*)")

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

        object_id = f"{postcode}-{huisnummer}{toevoeging}"
        listings[object_id] = FundaListing(
            object_id=object_id,
            url=f"https://www.funda.nl/zoeken/koop/?selected_area=%5B%22{postcode}%22%5D",
            straatnaam=adres_match.group("straat").strip(),
            huisnummer=huisnummer,
            toevoeging=toevoeging,
            postcode=postcode,
            woonplaats=postcode_match.group("plaats").strip(),
            prijs=prijs,
            eerst_gezien_override=_bepaal_eerst_gezien(blok, vandaag),
        )

    return list(listings.values()), fouten


def parse_bestand(tekst: str) -> tuple[list[FundaListing], list[str]]:
    """Herkent automatisch welk formaat het is: eerst geprobeerd als ruwe
    funda-kopieer-plak-tekstdump; levert dat niets op, dan als het simpele
    "POSTCODE HUISNUMMER [funda-link]"-per-regel-formaat."""
    listings, fouten = parse_funda_tekstdump(tekst)
    if listings:
        return listings, fouten
    return parse_regels(tekst.splitlines())
