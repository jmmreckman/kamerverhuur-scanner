from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import Message

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


@dataclass(frozen=True)
class FundaListing:
    object_id: str
    url: str
    woonplaats: str
    straatnaam: str | None
    huisnummer: str | None

    @property
    def adres_bekend(self) -> bool:
        return self.straatnaam is not None and self.huisnummer is not None


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


def extract_listings_from_email_body(body: str) -> list[FundaListing]:
    listings: dict[str, FundaListing] = {}
    for raw_url in _FUNDA_URL_ZOEKER.findall(body):
        listing = parse_funda_link(raw_url)
        if listing is not None:
            listings[listing.object_id] = listing
    return list(listings.values())


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


def fetch_recent_funda_listings(config: Config, lookback_days: int = 3) -> list[FundaListing]:
    with imaplib.IMAP4_SSL(config.imap_host) as imap:
        imap.login(config.gmail_address, config.gmail_app_password)
        imap.select(config.funda_mail_folder)

        since = (datetime.now() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f'(SINCE "{since}" HEADER FROM "funda")')
        if status != "OK":
            raise RuntimeError(f"IMAP-zoekopdracht mislukt: {status}")

        message_ids = data[0].split()
        all_listings: dict[str, FundaListing] = {}
        for msg_id in message_ids:
            status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            body = _get_body(msg)
            for listing in extract_listings_from_email_body(body):
                all_listings[listing.object_id] = listing

        return list(all_listings.values())
