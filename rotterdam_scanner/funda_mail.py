from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import Message
from email.header import decode_header

from .config import Config

# Funda-detail-URL's komen in twee bekende vormen voor. We ondersteunen beide, en
# als een link geen van beide patronen matcht, laten we hem niet stilzwijgend vallen:
# de aanroepende code kan dan alsnog de kale URL tonen voor handmatige controle.
_URL_PATTERN_NIEUW = re.compile(
    r"https://www\.funda\.nl/detail/koop/(?P<woonplaats>[a-z0-9-]+)/huis-(?P<slug>[a-z0-9-]+)/(?P<object_id>\d+)/?"
)
_URL_PATTERN_OUD = re.compile(
    r"https://www\.funda\.nl/koop/(?P<woonplaats>[a-z0-9-]+)/huis-(?P<object_id>\d+)-(?P<slug>[a-z0-9-]+)/?"
)
_HUISNUMMER_SUFFIX = re.compile(r"^(?P<straat>[a-z0-9-]+?)-(?P<huisnummer>\d+[a-z]?(?:-\d+)?)$")

_FUNDA_URL_ZOEKER = re.compile(r'href=["\']?(https://www\.funda\.nl/[^"\'\s>]+)', re.IGNORECASE)

# Best-effort: de prijs staat ergens in de opmaak rond de link van een woning in de
# e-mail. We zoeken in een venster van tekst na elke link, begrensd door de eerst-
# volgende woning-link (anders kan de prijs van het volgende huis hieraan toegeschreven
# worden). Dit is layout-afhankelijk en dus kwetsbaarder dan de URL-parsing hierboven —
# zie tools/test_email_parsing.py om dit te controleren/bij te stellen.
_ZOEKVENSTER_LENGTE = 600
_TAG_RE = re.compile(r"<[^>]+>")
_PRIJS_RE = re.compile(r"€\s?([\d]{2,3}(?:[.,]\d{3})*)")

VERWIJDER_ONDERWERP_PREFIX = "Verwijder"
_VERWIJDER_ONDERWERP_RE = re.compile(r"verwijder\s+(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class FundaListing:
    object_id: str
    url: str
    woonplaats: str
    straatnaam: str | None
    huisnummer: str | None
    prijs: int | None = None

    @property
    def adres_bekend(self) -> bool:
        return self.straatnaam is not None and self.huisnummer is not None


@dataclass
class FundaMailScan:
    listings: list[FundaListing] = field(default_factory=list)


def parse_funda_link(url: str) -> FundaListing | None:
    match = _URL_PATTERN_NIEUW.match(url) or _URL_PATTERN_OUD.match(url)
    if not match:
        return None

    groups = match.groupdict()
    slug_match = _HUISNUMMER_SUFFIX.match(groups["slug"])
    straatnaam = None
    huisnummer = None
    if slug_match:
        straatnaam = slug_match.group("straat").replace("-", " ").strip().title()
        huisnummer = slug_match.group("huisnummer")

    return FundaListing(
        object_id=groups["object_id"],
        url=url,
        woonplaats=groups["woonplaats"].replace("-", " ").title(),
        straatnaam=straatnaam,
        huisnummer=huisnummer,
    )


def _extract_prijs(venster: str) -> int | None:
    match = _PRIJS_RE.search(venster)
    if not match:
        return None
    cijfers = re.sub(r"[.,]", "", match.group(1))
    try:
        return int(cijfers)
    except ValueError:
        return None


def scan_email_body(body: str) -> FundaMailScan:
    listings: dict[str, FundaListing] = {}

    matches = list(_FUNDA_URL_ZOEKER.finditer(body))
    for i, match in enumerate(matches):
        raw_url = match.group(1)
        listing = parse_funda_link(raw_url)
        if listing is None:
            continue

        # Begrens het zoekvenster tot waar de eerstvolgende woning-link begint, anders
        # kan de prijs van het volgende huis per ongeluk aan dit huis toegeschreven
        # worden in compacte lay-outs met meerdere huizen vlak na elkaar.
        volgende_start = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        venster_eind = min(match.end() + _ZOEKVENSTER_LENGTE, volgende_start)
        venster = _TAG_RE.sub(" ", body[match.end() : venster_eind])

        prijs = _extract_prijs(venster)
        if prijs is not None and listing.object_id not in listings:
            listing = FundaListing(
                object_id=listing.object_id,
                url=listing.url,
                woonplaats=listing.woonplaats,
                straatnaam=listing.straatnaam,
                huisnummer=listing.huisnummer,
                prijs=prijs,
            )
        listings[listing.object_id] = listing

    return FundaMailScan(listings=list(listings.values()))


def extract_listings_from_email_body(body: str) -> list[FundaListing]:
    return scan_email_body(body).listings


def _get_body(msg: Message) -> str:
    if msg.is_multipart():
        html_part = None
        text_part = None
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/html" and html_part is None:
                html_part = part
            elif content_type == "text/plain" and text_part is None:
                text_part = part
        chosen = html_part or text_part
        if chosen is None:
            return ""
        payload = chosen.get_payload(decode=True) or b""
        charset = chosen.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")

    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def fetch_recent_funda_mail_scan(config: Config, lookback_days: int = 3) -> FundaMailScan:
    with imaplib.IMAP4_SSL(config.imap_host) as imap:
        imap.login(config.gmail_address, config.gmail_app_password)
        imap.select(config.funda_mail_folder)

        since = (datetime.now() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f'(SINCE "{since}" HEADER FROM "funda")')
        if status != "OK":
            raise RuntimeError(f"IMAP-zoekopdracht mislukt: {status}")

        message_ids = data[0].split()
        alle_listings: dict[str, FundaListing] = {}
        for msg_id in message_ids:
            status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            body = _get_body(msg)
            scan = scan_email_body(body)
            for listing in scan.listings:
                if listing.object_id in alle_listings and listing.prijs is None:
                    continue  # niet een eerder gevonden prijs overschrijven met "onbekend"
                alle_listings[listing.object_id] = listing

        return FundaMailScan(listings=list(alle_listings.values()))


def fetch_recent_funda_listings(config: Config, lookback_days: int = 3) -> list[FundaListing]:
    return fetch_recent_funda_mail_scan(config, lookback_days).listings


def _decode_subject(raw_subject: str | None) -> str:
    if not raw_subject:
        return ""
    parts = decode_header(raw_subject)
    decoded = ""
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded += text.decode(charset or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded


def fetch_verwijder_commandos(config: Config) -> set[str]:
    """Zoekt naar mails met onderwerp "Verwijder <object_id>" (zie de verwijder-link in
    het rapport) en geeft de object_id's terug die de gebruiker zo heeft opgevraagd om
    uit de lijst te halen."""
    with imaplib.IMAP4_SSL(config.imap_host) as imap:
        imap.login(config.gmail_address, config.gmail_app_password)
        imap.select(config.funda_mail_folder)

        status, data = imap.search(None, f'SUBJECT "{VERWIJDER_ONDERWERP_PREFIX}"')
        if status != "OK":
            raise RuntimeError(f"IMAP-zoekopdracht mislukt: {status}")

        object_ids: set[str] = set()
        for msg_id in data[0].split():
            status, msg_data = imap.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            header_bytes = msg_data[0][1]
            subject = _decode_subject(
                email.message_from_bytes(header_bytes).get("Subject")
            )
            match = _VERWIJDER_ONDERWERP_RE.search(subject)
            if match:
                object_ids.add(match.group(1))

        return object_ids
