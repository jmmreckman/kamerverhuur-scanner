"""Postvak info@ - een eenvoudig webmail-achtig postvak binnen Steenhub voor de
info@steenhub.nl-mailbox, zodat een beheerder de mail kan lezen en beantwoorden
zonder de Strato-webmail op te zoeken of alles naar privé door te sturen.

Bewust **live via IMAP** (geen eigen database/sync-service): Strato blijft de
bron van waarheid, dus wat je hier leest/markeert/stert is meteen ook zo in de
webmail - geen twee werkelijkheden, en geen migratie-/opslagrisico. Alle IMAP-
I/O gebeurt pas bij een expliciete actie (nooit bij het opstarten van de app).

De creds zijn dezelfde als voor uitgaande mail: `SMTP_USERNAME`/`SMTP_PASSWORD`
(= info@steenhub.nl) op `STEENHUB_IMAP_HOST` (default imap.strato.com). Vereist
dat IMAP voor dat postvak aanstaat bij Strato.

De pure parse-functies (`parse_headers`, `parse_bericht`, `antwoord_velden`)
werken op rauwe bytes en zijn los testbaar; de IMAP-functies zijn dunne I/O
eromheen. Hergebruikt `webapp/mail_inname.py` voor de verbinding.
"""
from __future__ import annotations

import re
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime

from kamerverhuur_scanner.config import Config

from . import mail_inname

MailFout = mail_inname.MailInnameError

_UID_RE = re.compile(rb"UID (\d+)")
_FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")
_HEADER_VELDEN = "(FROM SUBJECT DATE MESSAGE-ID)"


# --- Creds / verbinding ---------------------------------------------------

def creds_aanwezig(config: Config) -> bool:
    """Of er genoeg is om info@ via IMAP te lezen (dezelfde creds als uitgaande
    mail). Zonder dit tonen we het postvak netjes als 'nog niet ingesteld'."""
    return bool(config.smtp_username and config.smtp_password and config.steenhub_imap_host)


def verbind(config: Config):
    """Open een IMAP-verbinding naar het info@-postvak. Aanroeper sluit zelf
    (met `imap.logout()`), bij voorkeur in een try/finally."""
    if not creds_aanwezig(config):
        raise MailFout("Het info@-postvak is nog niet ingesteld (SMTP_USERNAME/SMTP_PASSWORD ontbreekt).")
    return mail_inname.verbind(config.steenhub_imap_host, config.smtp_username, config.smtp_password)


# --- Pure parse-helpers (los testbaar) ------------------------------------

def _decode(waarde: str | None) -> str:
    if not waarde:
        return ""
    try:
        return str(make_header(decode_header(waarde)))
    except Exception:
        return waarde


def _afzender(from_header: str | None) -> tuple[str, str]:
    """(weergavenaam, e-mailadres) uit een From-header; naam valt terug op het adres."""
    naam, adres = parseaddr(from_header or "")
    naam = _decode(naam)
    return (naam or adres, adres)


def _datum_iso(date_header: str | None) -> str:
    if not date_header:
        return ""
    try:
        dt = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return ""
    if dt is None:
        return ""
    return dt.strftime("%d-%m-%Y %H:%M")


def parse_headers(ruwe_headers: bytes) -> dict:
    """Haal afzender/onderwerp/datum/message-id uit (alleen-headers) rauwe bytes."""
    msg = message_from_bytes(ruwe_headers)
    naam, adres = _afzender(msg.get("From"))
    return {
        "van_naam": naam,
        "van_adres": adres,
        "onderwerp": _decode(msg.get("Subject")) or "(geen onderwerp)",
        "datum": _datum_iso(msg.get("Date")),
        "message_id": (msg.get("Message-ID") or "").strip(),
    }


def _payload_str(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")


def html_naar_tekst(html: str) -> str:
    """Grove, VEILIGE omzetting van HTML-mail naar leesbare platte tekst (we tonen
    bewust nooit rauwe afzender-HTML - dat is een XSS-/tracking-risico). Strip
    script/style, zet <br>/<p> om naar witregels, verwijder tags, decodeer entiteiten."""
    import html as _html

    tekst = _STYLE_RE.sub(" ", html)
    tekst = re.sub(r"(?i)<br\s*/?>", "\n", tekst)
    tekst = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", tekst)
    tekst = _TAG_RE.sub("", tekst)
    tekst = _html.unescape(tekst)
    # meerdere lege regels/witruimte inklappen
    tekst = re.sub(r"[ \t]+\n", "\n", tekst)
    tekst = re.sub(r"\n{3,}", "\n\n", tekst)
    return tekst.strip()


def parse_bericht(ruwe_mail: bytes) -> dict:
    """Volledig bericht uit rauwe bytes: headers + leesbare platte-tekst body +
    lijst bijlagen (met index om later los te downloaden). Toont nooit rauwe HTML."""
    msg = message_from_bytes(ruwe_mail)
    naam, adres = _afzender(msg.get("From"))
    tekst = None
    html = None
    bijlagen: list[dict] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        bestandsnaam = part.get_filename()
        disp = str(part.get("Content-Disposition") or "").lower()
        ctype = (part.get_content_type() or "").lower()
        if bestandsnaam or "attachment" in disp:
            grootte = len(part.get_payload(decode=True) or b"")
            bijlagen.append({
                "index": len(bijlagen), "naam": _decode(bestandsnaam) or "bijlage",
                "mime": ctype or "application/octet-stream", "grootte": grootte,
            })
            continue
        if ctype == "text/plain" and tekst is None:
            tekst = _payload_str(part)
        elif ctype == "text/html" and html is None:
            html = _payload_str(part)
    if tekst is None or not tekst.strip():
        tekst = html_naar_tekst(html) if html else ""
    return {
        "van_naam": naam, "van_adres": adres,
        "onderwerp": _decode(msg.get("Subject")) or "(geen onderwerp)",
        "datum": _datum_iso(msg.get("Date")),
        "message_id": (msg.get("Message-ID") or "").strip(),
        "body": tekst, "bijlagen": bijlagen,
    }


def antwoord_velden(bericht: dict) -> dict:
    """Voorgevulde velden voor een antwoord: aan-adres, "Re: ..."-onderwerp en de
    threading-headers (In-Reply-To/References) op basis van het originele bericht."""
    onderwerp = bericht.get("onderwerp") or ""
    schoon = onderwerp if onderwerp.lower().startswith("re:") else f"Re: {onderwerp}".strip()
    mid = bericht.get("message_id") or ""
    headers = {}
    if mid:
        headers["In-Reply-To"] = mid
        headers["References"] = mid
    return {"aan": bericht.get("van_adres", ""), "onderwerp": schoon, "headers": headers}


# --- IMAP-I/O (dun) -------------------------------------------------------

def _meta(ruw: bytes) -> tuple[str, set[str]]:
    uid_m = _UID_RE.search(ruw or b"")
    flags_m = _FLAGS_RE.search(ruw or b"")
    uid = uid_m.group(1).decode() if uid_m else ""
    vlaggen = set((flags_m.group(1).decode() if flags_m else "").split())
    return uid, vlaggen


def lijst_recent(imap, aantal: int = 50) -> list[dict]:
    """De `aantal` nieuwste mails uit INBOX (nieuwste eerst), alleen headers +
    gelezen/belangrijk-vlag. Markeert niets (BODY.PEEK)."""
    imap.select("INBOX")
    status, data = imap.uid("search", None, "ALL")
    if status != "OK" or not data or not data[0]:
        return []
    uids = data[0].split()
    recent = uids[-aantal:]
    if not recent:
        return []
    verzoek = b",".join(recent)
    status, blok = imap.uid("fetch", verzoek, f"(FLAGS BODY.PEEK[HEADER.FIELDS {_HEADER_VELDEN}])")
    if status != "OK" or not blok:
        return []
    resultaat = []
    for deel in blok:
        if not isinstance(deel, tuple) or len(deel) != 2:
            continue
        uid, vlaggen = _meta(deel[0])
        kop = parse_headers(deel[1] or b"")
        kop["uid"] = uid
        kop["gelezen"] = "\\Seen" in vlaggen
        kop["belangrijk"] = "\\Flagged" in vlaggen
        resultaat.append(kop)
    resultaat.sort(key=lambda m: int(m["uid"] or 0), reverse=True)
    return resultaat


def haal_bericht(imap, uid: str) -> dict | None:
    """Volledig bericht voor deze UID (markeert niets; de route markeert zelf
    gelezen na succesvol tonen). None als de UID niet bestaat."""
    imap.select("INBOX")
    status, blok = imap.uid("fetch", uid, "(FLAGS BODY.PEEK[])")
    if status != "OK" or not blok:
        return None
    for deel in blok:
        if isinstance(deel, tuple) and len(deel) == 2:
            _u, vlaggen = _meta(deel[0])
            bericht = parse_bericht(deel[1] or b"")
            bericht["uid"] = uid
            bericht["gelezen"] = "\\Seen" in vlaggen
            bericht["belangrijk"] = "\\Flagged" in vlaggen
            return bericht
    return None


def haal_bijlage(imap, uid: str, index: int) -> tuple[str, str, bytes] | None:
    """(bestandsnaam, mimetype, inhoud) van de `index`-de bijlage, of None."""
    imap.select("INBOX")
    status, blok = imap.uid("fetch", uid, "(BODY.PEEK[])")
    if status != "OK" or not blok:
        return None
    ruw = next((d[1] for d in blok if isinstance(d, tuple) and len(d) == 2), None)
    if not ruw:
        return None
    msg = message_from_bytes(ruw)
    teller = 0
    for part in msg.walk():
        if part.is_multipart():
            continue
        bestandsnaam = part.get_filename()
        disp = str(part.get("Content-Disposition") or "").lower()
        if bestandsnaam or "attachment" in disp:
            if teller == index:
                inhoud = part.get_payload(decode=True) or b""
                return (_decode(bestandsnaam) or "bijlage", (part.get_content_type() or "application/octet-stream"), inhoud)
            teller += 1
    return None


def _store(imap, uid: str, plus: bool, vlag: str) -> None:
    imap.select("INBOX")
    imap.uid("store", uid, ("+FLAGS" if plus else "-FLAGS"), f"({vlag})")


def markeer_gelezen(imap, uid: str, gelezen: bool = True) -> None:
    _store(imap, uid, gelezen, "\\Seen")


def zet_belangrijk(imap, uid: str, belangrijk: bool) -> None:
    _store(imap, uid, belangrijk, "\\Flagged")


def tel_ongelezen(imap) -> int:
    imap.select("INBOX")
    status, data = imap.uid("search", None, "UNSEEN")
    if status != "OK" or not data or not data[0]:
        return 0
    return len(data[0].split())


def tel_belangrijk(imap) -> int:
    imap.select("INBOX")
    status, data = imap.uid("search", None, "FLAGGED")
    if status != "OK" or not data or not data[0]:
        return 0
    return len(data[0].split())
