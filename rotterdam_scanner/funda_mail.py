from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.header import decode_header
from email.message import Message

from .config import Config

# Funda's e-mails wikkelen elke link (ook de woning-links) in een Iterable-
# clicktracking-URL (links.funda.nl/s/c/...); die bevat geen herleidbare
# adres-/object-informatie en is zelf ook niet zomaar te volgen (403 op
# niet-browserverkeer -- daar gaan we dus niet aan zitten). We halen adres,
# postcode/plaats en prijs daarom uit de zichtbare tekst rond elke link, en
# gebruiken de link zelf alleen als kant-en-klare klik-URL voor het rapport.
_LISTING_LINK_RE = re.compile(
    r'<a\s+[^>]*href="(?P<url>https?://[^"]+)"[^>]*>\s*<span[^>]*>(?P<adres>[^<]+)</span>\s*</a>',
    re.IGNORECASE,
)
_ADRES_SPLITS_RE = re.compile(r"^(?P<straat>.+?)\s+(?P<huisnummer>\d+)\s*(?P<toevoeging>[A-Za-z]?(?:-\d+)?)\s*$")
_POSTCODE_PLAATS_RE = re.compile(r"(?P<postcode>\d{4}\s?[A-Z]{2})\s+(?P<plaats>[A-Za-zÀ-ÿ.'\- ]+)")
_PRIJS_RE = re.compile(r"€\s?([\d]{2,3}(?:[.,]\d{3})*)")
_BEKIJK_ALLE_RE = re.compile(r"Bekijk alle (\d+) woning", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

# Ruim bemeten venster: in een echte funda-mail zit de prijs ~500 tekens (ruwe HTML)
# na de adres-link. Begrensd door de eerstvolgende woning-link, dus dit loopt nooit
# over naar het volgende huis.
_ZOEKVENSTER_LENGTE = 2000

VERWIJDER_ONDERWERP_PREFIX = "Verwijder"
_VERWIJDER_ONDERWERP_RE = re.compile(r"verwijder\s+([0-9a-z\-]+)", re.IGNORECASE)


@dataclass(frozen=True)
class FundaListing:
    object_id: str
    url: str
    straatnaam: str | None
    huisnummer: str | None
    toevoeging: str
    postcode: str | None
    woonplaats: str | None
    prijs: int | None = None
    # Alleen gezet door de handmatige tekstdump-parser, die soms een "Sinds X
    # weken/maanden" of exacte datum bij een woning kan lezen. Zo niet: None, en dan
    # gebruikt de pipeline gewoon vandaag als eerst_gezien (net als bij nieuwe
    # woningen uit de dagelijkse e-mail-alert, die altijd echt nieuw zijn).
    eerst_gezien_override: date | None = None

    @property
    def adres_bekend(self) -> bool:
        return self.postcode is not None and self.huisnummer is not None

    @property
    def weergavenaam(self) -> str:
        if self.straatnaam and self.huisnummer:
            adres = f"{self.straatnaam} {self.huisnummer}{self.toevoeging}"
            if self.postcode and self.woonplaats:
                return f"{adres}, {self.postcode} {self.woonplaats}"
            return adres
        return self.url


@dataclass
class FundaMailScan:
    listings: list[FundaListing] = field(default_factory=list)
    waarschuwingen: list[str] = field(default_factory=list)


def _split_adres(adres_tekst: str) -> tuple[str | None, str | None, str]:
    match = _ADRES_SPLITS_RE.match(adres_tekst.strip())
    if not match:
        return None, None, ""
    return (
        match.group("straat").strip(),
        match.group("huisnummer"),
        match.group("toevoeging").strip().upper(),
    )


def _maak_object_id(postcode: str | None, huisnummer: str | None, toevoeging: str) -> str | None:
    if not postcode or not huisnummer:
        return None
    return f"{postcode.replace(' ', '').upper()}-{huisnummer}{toevoeging}"


def scan_email_body(body: str) -> FundaMailScan:
    listings: dict[str, FundaListing] = {}
    onherkend_urls: list[str] = []

    matches = [m for m in _LISTING_LINK_RE.finditer(body) if re.search(r"\d", m.group("adres"))]
    for i, match in enumerate(matches):
        url = match.group("url")
        straatnaam, huisnummer, toevoeging = _split_adres(match.group("adres"))

        volgende_start = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        venster_eind = min(match.end() + _ZOEKVENSTER_LENGTE, volgende_start)
        venster = _TAG_RE.sub(" ", body[match.end() : venster_eind])

        postcode_match = _POSTCODE_PLAATS_RE.search(venster)
        postcode = postcode_match.group("postcode").replace(" ", "") if postcode_match else None
        woonplaats = postcode_match.group("plaats").strip() if postcode_match else None

        prijs_match = _PRIJS_RE.search(venster)
        prijs = int(re.sub(r"[.,]", "", prijs_match.group(1))) if prijs_match else None

        object_id = _maak_object_id(postcode, huisnummer, toevoeging)
        if object_id is None:
            onherkend_urls.append(url)
            continue

        if object_id in listings and listings[object_id].prijs is not None:
            continue  # niet een eerder gevonden prijs overschrijven met "onbekend"

        listings[object_id] = FundaListing(
            object_id=object_id,
            url=url,
            straatnaam=straatnaam,
            huisnummer=huisnummer,
            toevoeging=toevoeging,
            postcode=postcode,
            woonplaats=woonplaats,
            prijs=prijs,
        )

    waarschuwingen = []
    aangekondigd = sum(int(n) for n in _BEKIJK_ALLE_RE.findall(body))
    if aangekondigd and len(listings) < aangekondigd:
        waarschuwingen.append(
            f"Funda-mail kondigt in totaal {aangekondigd} woning(en) aan via 'Bekijk alle...'-knoppen, "
            f"maar er konden er maar {len(listings)} individueel herkend worden. Mogelijk toont funda "
            "meer dan de standaard 2 woningen per zoekopdracht niet los in de mail -- check je "
            "Funda-account handmatig voor deze dag, of splits je zoekopdracht in kleinere stukken."
        )
    for url in onherkend_urls:
        waarschuwingen.append(f"Kon adres niet herleiden uit e-mailtekst voor link: {url}")

    return FundaMailScan(listings=list(listings.values()), waarschuwingen=waarschuwingen)


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
        alle_waarschuwingen: list[str] = []
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
            alle_waarschuwingen.extend(scan.waarschuwingen)

        return FundaMailScan(listings=list(alle_listings.values()), waarschuwingen=alle_waarschuwingen)


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
                object_ids.add(match.group(1).upper())

        return object_ids
