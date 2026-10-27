"""Dagelijkse inname (Fase 2): leest de eigen Steenhub-mailboxen uit en koppelt
binnengekomen mail aan de juiste huurder.

- onderhoud@steenhub.nl  -> opent een onderhoudsticket bij de huurder + logt de mail.
- communicatie@steenhub.nl -> logt de mail bij de huurder en laat de AI beoordelen
  of er een antwoord/taak nodig is (concept in de goedkeuringswachtrij).

Kernidee voor de koppeling: we kijken NIET naar 'van wie komt de mail' (bij
doorsturen ben jij de afzender), maar zoeken in de hele mail - afzender, aan, cc
en de tekst - naar een e-mailadres dat bij een bekende huurder hoort. Zo werkt
het zowel als de huurder zelf mailt als wanneer jij een mail doorstuurt.

De pure delen (adressen uit een mail halen) staan los van IMAP, zodat ze in de
sandbox getest kunnen worden. De service-loop staat in scripts/mail_inname.py.
"""
from __future__ import annotations

import email
import imaplib
import re
from email.message import Message

from .mail_import import adres_uit, kies_tekst

# Simpel maar ruim e-mailadres-patroon (voor het terugvinden van een huurder-adres
# in de doorgestuurde tekst). We valideren niet streng - een adres telt pas als het
# ook echt bij een bekend contact hoort.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def adressen_in_mail(raw: bytes) -> list[str]:
    """Alle e-mailadressen (lowercase, zonder dubbele, volgorde behouden) die in
    de mail voorkomen: From/To/Cc-headers eerst, daarna de adressen uit de body.
    De header-adressen staan vooraan zodat een directe afzender voorrang krijgt
    boven een adres dat ergens in een handtekening of citaat staat."""
    msg = email.message_from_bytes(raw)
    gevonden: list[str] = []

    def voeg_toe(adres: str) -> None:
        adres = (adres or "").strip().lower()
        if adres and adres not in gevonden:
            gevonden.append(adres)

    for header in ("From", "To", "Cc"):
        for waarde in msg.get_all(header, []):
            # Een header kan meerdere adressen bevatten.
            for stuk in _EMAIL_RE.findall(waarde or ""):
                voeg_toe(stuk)
            voeg_toe(adres_uit(waarde))

    for stuk in _EMAIL_RE.findall(kies_tekst(msg) or ""):
        voeg_toe(stuk)
    return gevonden


def parse_inkomend(raw: bytes) -> dict:
    """Velden van een binnengekomen mail voor de tijdlijn/ticket. Richting is
    altijd 'in' (het is een binnengekomen of doorgestuurde mail aan Steenhub)."""
    msg = email.message_from_bytes(raw)
    from .mail_import import _header  # hergebruik de header-decodering
    from email.utils import parsedate_to_datetime

    datum_iso = None
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        if dt is not None:
            datum_iso = dt.isoformat()
    except (TypeError, ValueError):
        datum_iso = None
    return {
        "van": adres_uit(msg.get("From")) or None,
        "naar": adres_uit(msg.get("To")) or None,
        "onderwerp": (_header(msg, "Subject") or None),
        "datum": datum_iso,
        "body": kies_tekst(msg),
        "message_id": (msg.get("Message-ID") or "").strip() or None,
        "richting": "in",
    }


# --- IMAP (impuur) ----------------------------------------------------------

class MailInnameError(RuntimeError):
    pass


def verbind(host: str, gebruiker: str, wachtwoord: str) -> imaplib.IMAP4_SSL:
    try:
        imap = imaplib.IMAP4_SSL(host)
        imap.login(gebruiker, wachtwoord)
    except (imaplib.IMAP4.error, OSError) as exc:
        raise MailInnameError(f"Kon niet inloggen op {host} als {gebruiker}: {exc}") from exc
    try:
        imap.sock.settimeout(120)
    except OSError:
        pass
    return imap


def haal_ongelezen(imap: imaplib.IMAP4_SSL) -> list[tuple[bytes, bytes]]:
    """Geeft (uid, rauwe-mail) voor alle ongelezen berichten in INBOX. Markeert
    niets; dat doet de aanroeper pas na succesvolle verwerking (markeer_gelezen)."""
    imap.select("INBOX")
    status, data = imap.uid("search", None, "UNSEEN")
    if status != "OK" or not data or not data[0]:
        return []
    uids = data[0].split()
    resultaat: list[tuple[bytes, bytes]] = []
    for uid in uids:
        # PEEK: lezen zonder de mail als gelezen te markeren (dat doen we bewust
        # pas na verwerking, zodat een crash een mail niet stiekem 'gelezen' laat).
        st, blok = imap.uid("fetch", uid, "(BODY.PEEK[])")
        if st != "OK" or not blok:
            continue
        for deel in blok:
            if isinstance(deel, tuple) and len(deel) == 2:
                resultaat.append((uid, deel[1]))
                break
    return resultaat


def markeer_gelezen(imap: imaplib.IMAP4_SSL, uid: bytes) -> None:
    try:
        imap.uid("store", uid, "+FLAGS", "(\\Seen)")
    except imaplib.IMAP4.error:
        pass
