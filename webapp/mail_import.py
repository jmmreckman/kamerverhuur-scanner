"""Inlezen van e-mail via IMAP voor de communicatiemodule.

Fase 1b (nu): de eenmalige backfill van historische huurder-communicatie uit het
persoonlijke Gmail-account van de beheerder (zie scripts/gmail_backfill.py). Per
huurder zoeken we op e-mailadres in "All Mail" (zowel verzonden als ontvangen),
parseren de berichten en zetten ze in de communicatie-db.

De *pure* delen (adres uit een header halen, een rauwe e-mail parsen, de IMAP-
zoekcriteria bouwen) staan los van de netwerk-/IMAP-aanroepen, zodat ze in de
sandbox getest kunnen worden zonder mailserver.

Later (Fase 2) kan dezelfde parsing hergebruikt worden voor de dagelijkse inname
van info@/onderhoud@.
"""
from __future__ import annotations

import email
import imaplib
import logging
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime

from kamerverhuur_scanner.config import Config

logger = logging.getLogger(__name__)

_TIMEOUT = 60


class MailImportError(RuntimeError):
    """IMAP niet (volledig) ingesteld, of inlezen is mislukt."""


# --- pure helpers (los testbaar) -------------------------------------------

def adres_uit(header: str | None) -> str:
    """Haalt het kale e-mailadres (lowercase) uit een From/To-header."""
    if not header:
        return ""
    return (parseaddr(header)[1] or "").strip().lower()


def kies_tekst(msg: Message) -> str:
    """De platte-tekst-body van een (eventueel multipart) e-mail. Pakt het eerste
    text/plain-deel; valt anders terug op een ruwe text/html (zonder opmaak-strip,
    bewust simpel) of een lege string."""
    html_terugval = ""
    if msg.is_multipart():
        for deel in msg.walk():
            if deel.get_content_maintype() == "multipart":
                continue
            if deel.get("Content-Disposition", "").strip().lower().startswith("attachment"):
                continue
            ctype = deel.get_content_type()
            tekst = _decodeer(deel)
            if ctype == "text/plain" and tekst.strip():
                return tekst.strip()
            if ctype == "text/html" and not html_terugval:
                html_terugval = tekst
    else:
        return _decodeer(msg).strip()
    return html_terugval.strip()


def _decodeer(deel: Message) -> str:
    inhoud = deel.get_payload(decode=True)
    if inhoud is None:
        payload = deel.get_payload()
        return payload if isinstance(payload, str) else ""
    charset = deel.get_content_charset() or "utf-8"
    try:
        return inhoud.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return inhoud.decode("utf-8", errors="replace")


def parse_email(raw: bytes, eigen_adres: str) -> dict:
    """Parseert een rauwe e-mail (bytes) tot een dict met de velden die de
    communicatie-db nodig heeft. `eigen_adres` (het Gmail-adres van de beheerder)
    bepaalt de richting: staat dat in de afzender, dan is het een verzonden
    bericht (uit), anders ontvangen (in)."""
    msg = email.message_from_bytes(raw)
    van = adres_uit(msg.get("From"))
    naar = adres_uit(msg.get("To"))
    eigen = (eigen_adres or "").strip().lower()
    richting = "uit" if eigen and eigen == van else "in"
    datum_iso = None
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        if dt is not None:
            datum_iso = dt.isoformat()
    except (TypeError, ValueError):
        datum_iso = None
    return {
        "van": van or None,
        "naar": naar or None,
        "onderwerp": (_header(msg, "Subject") or None),
        "datum": datum_iso,
        "body": kies_tekst(msg),
        "message_id": (msg.get("Message-ID") or "").strip() or None,
        "richting": richting,
    }


def _header(msg: Message, naam: str) -> str:
    """Gedecodeerde headerwaarde (bv. een onderwerp met =?utf-8?..?= encoding)."""
    ruw = msg.get(naam)
    if not ruw:
        return ""
    from email.header import decode_header, make_header
    try:
        return str(make_header(decode_header(ruw))).strip()
    except (ValueError, LookupError):
        return ruw.strip()


def imap_zoek_criteria(adres: str) -> list[str]:
    """IMAP-SEARCH-criteria voor alles van of aan een adres (verzonden +
    ontvangen)."""
    return ["OR", "FROM", adres, "TO", adres]


# --- IMAP (netwerk) ---------------------------------------------------------

def verbind_gmail(config: Config) -> imaplib.IMAP4_SSL:
    """Logt in op Gmail via IMAP en selecteert de 'All Mail'-map (ook als die in
    een Nederlands account anders heet - we zoeken 'm op de \\All-special-use-
    vlag). Gooit MailImportError als de Gmail-koppeling niet is ingesteld."""
    if not (config.gmail_imap_user and config.gmail_imap_password):
        raise MailImportError(
            "Gmail-import is niet ingesteld - zet GMAIL_IMAP_USER en "
            "GMAIL_IMAP_PASSWORD (een app-wachtwoord) in de env."
        )
    try:
        imap = imaplib.IMAP4_SSL(config.gmail_imap_host, timeout=_TIMEOUT)
        imap.login(config.gmail_imap_user, config.gmail_imap_password)
    except (imaplib.IMAP4.error, OSError) as exc:
        raise MailImportError(f"Inloggen op Gmail (IMAP) is mislukt: {exc}") from exc
    map_naam = _vind_all_mail(imap)
    imap.select(f'"{map_naam}"', readonly=True)
    # Harde socket-time-out op álle vervolgbewerkingen (fetch kan anders eindeloos
    # blijven wachten als de server stilvalt).
    try:
        imap.sock.settimeout(120)
    except (AttributeError, OSError):
        pass
    return imap


def _vind_all_mail(imap: imaplib.IMAP4_SSL) -> str:
    """Zoekt de 'All Mail'-map via de \\All-special-use-vlag; valt terug op
    '[Gmail]/All Mail'."""
    try:
        status, regels = imap.list()
        if status == "OK":
            for ruw in regels:
                regel = ruw.decode(errors="replace") if isinstance(ruw, bytes) else str(ruw)
                if "\\All" in regel:
                    # Mapnaam staat als laatste, tussen quotes of na de laatste spatie.
                    if '"' in regel:
                        return regel.split('"')[-2]
                    return regel.split()[-1]
    except imaplib.IMAP4.error:
        pass
    return "[Gmail]/All Mail"


# Per bericht halen we alleen de eerste ~200 KB op: headers + de tekst-body zitten
# vooraan de mail, bijlagen komen daarna. Zo downloaden we nooit dikke bijlagen
# (die we toch niet opslaan) en blijft het ophalen snel, ook bij veel grote mails.
_MAX_FETCH_BYTES = 200_000


def _eerste_bytes(blok) -> bytes | None:
    """Haalt de ruwe berichtbytes uit een imaplib-fetch-respons."""
    if not blok:
        return None
    for item in blok:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    return None


def importeer_voor_adres(
    db, imap: imaplib.IMAP4_SSL, *, contact_id: int, pand_slug: str, adres: str, eigen_adres: str,
) -> int:
    """Zoekt in de geselecteerde map alle berichten van/aan `adres`, parseert de
    tekst (eerste ~200 KB, dus zonder bijlagen te downloaden) en zet ze in de
    communicatie-db (dedup op Message-ID). Geeft het aantal nieuw toegevoegde
    berichten terug; logt de voortgang."""
    from . import communicatie_db

    adres = (adres or "").strip().lower()
    if not adres:
        return 0
    status, data = imap.search(None, *imap_zoek_criteria(adres))
    if status != "OK" or not data or not data[0]:
        logger.info("    0 berichten gevonden voor %s", adres)
        return 0
    nums = data[0].split()
    totaal = len(nums)
    logger.info("    %d bericht(en) gevonden voor %s, ophalen...", totaal, adres)

    toegevoegd = 0
    for i, num in enumerate(nums, 1):
        try:
            status, blok = imap.fetch(num, "(BODY.PEEK[]<0.%d>)" % _MAX_FETCH_BYTES)
        except (imaplib.IMAP4.error, OSError) as exc:
            logger.warning("    bericht %s overslaan (ophalen mislukt: %s)", num, exc)
            continue
        raw = _eerste_bytes(blok)
        if not raw:
            continue
        p = parse_email(raw, eigen_adres)
        nieuw = communicatie_db.voeg_bericht_toe(
            db, contact_id=contact_id, pand_slug=pand_slug, kanaal="gmail-historie",
            richting=p["richting"], van=p["van"], naar=p["naar"], onderwerp=p["onderwerp"],
            body=p["body"], datum=p["datum"], bron="gmail-backfill", message_id=p["message_id"],
        )
        if nieuw is not None:
            toegevoegd += 1
        if i % 50 == 0:
            logger.info("    %d/%d verwerkt...", i, totaal)
    return toegevoegd
