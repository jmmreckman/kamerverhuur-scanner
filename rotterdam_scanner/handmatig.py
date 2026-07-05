from __future__ import annotations

import re

from .funda_mail import FundaListing

# Verwacht formaat per regel: "POSTCODE HUISNUMMER[TOEVOEGING] [funda-link]", bijv.
# "3073KJ 47A" of "3078 CN 44 https://www.funda.nl/detail/koop/rotterdam/huis-.../123/".
# Postcode + huisnummer is ondubbelzinnig (precies één adres in Nederland) en dat is
# alles wat nodig is om de woning door dezelfde checks te halen als de dagelijkse run.
_REGEL_RE = re.compile(
    r"^(?P<postcode>\d{4}\s?[A-Za-z]{2})\s+(?P<huisnummer>\d+)(?P<toevoeging>[A-Za-z0-9\-]*)"
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
