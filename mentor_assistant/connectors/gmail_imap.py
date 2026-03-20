"""
Gmail IMAP/SMTP connector voor inkomende mails en het versturen van de briefing.

Gebruikt:
  - IMAP (imap.gmail.com:993) om mails te lezen
  - SMTP (smtp.gmail.com:587) om de briefing te versturen

Vereist een Gmail App-wachtwoord (geen gewoon wachtwoord):
  myaccount.google.com → Beveiliging → App-wachtwoorden
"""
import email
import imaplib
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..config import GMAIL_APP_PASSWORD, GMAIL_EMAIL, MENTOR_EMAIL
from ..database import get_sync_status, sla_communicatie_op, update_sync_log

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _verbind_imap() -> imaplib.IMAP4_SSL:
    """Open een IMAP verbinding met Gmail."""
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    conn.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
    return conn


def sync_gmail():
    """
    Haal nieuwe mails op uit Gmail Inbox via IMAP.
    Slaat inkomende mails op in de database.
    Retourneert aantal nieuwe berichten.
    """
    print("Synchroniseren Gmail mails...")
    sync_status = get_sync_status("gmail")

    # Bepaal vanaf welke datum we zoeken
    if sync_status and sync_status.get("laatste_sync"):
        try:
            sinds_dt = datetime.fromisoformat(sync_status["laatste_sync"])
        except (ValueError, TypeError):
            sinds_dt = datetime.now(timezone.utc) - timedelta(days=30)
    else:
        sinds_dt = datetime.now(timezone.utc) - timedelta(days=30)

    # IMAP datum-formaat: DD-Mon-YYYY
    sinds_str = sinds_dt.strftime("%d-%b-%Y")

    try:
        conn = _verbind_imap()
        conn.select("INBOX")

        # Zoek emails vanaf de datum
        _status, uids = conn.uid("search", None, f'SINCE "{sinds_str}"')
        uid_lijst = uids[0].split() if uids[0] else []

        nieuwe_mails = 0
        for uid in uid_lijst:
            try:
                _status, data = conn.uid("fetch", uid, "(RFC822)")
                if not data or not data[0]:
                    continue
                raw = data[0][1]
                msg = email.message_from_bytes(raw)
                _verwerk_gmail_mail(msg, uid.decode())
                nieuwe_mails += 1
            except Exception as e:
                print(f"  Mail {uid} overgeslagen: {e}")
                continue

        conn.logout()
        update_sync_log("gmail", laatste_item_id=None)
        print(f"  → {nieuwe_mails} nieuwe mail(s) opgeslagen.")
        return nieuwe_mails

    except Exception as e:
        update_sync_log("gmail", status="fout", foutmelding=str(e))
        raise


def _verwerk_gmail_mail(msg: email.message.Message, uid: str):
    """Verwerk één Gmail bericht naar database record."""
    van = email.utils.parseaddr(msg.get("From", ""))[1]
    aan = msg.get("To", "")
    onderwerp = _decodeer_header(msg.get("Subject", ""))
    datum_str = msg.get("Date", "")

    # Datum parsen
    try:
        datum_tuple = email.utils.parsedate_to_datetime(datum_str)
        datum = datum_tuple.isoformat()
    except Exception:
        datum = datetime.now().isoformat()

    # Body extraheren
    inhoud = _haal_body_op(msg)

    sla_communicatie_op({
        "bron": "gmail",
        "extern_id": uid,
        "richting": "inkomend",
        "van_email": van,
        "aan_email": aan,
        "onderwerp": onderwerp,
        "inhoud": inhoud[:10000],
        "datum": datum,
    })


def _haal_body_op(msg: email.message.Message) -> str:
    """Haal platte tekst uit een e-mailbericht (HTML wordt gestript)."""
    tekst = ""
    if msg.is_multipart():
        for deel in msg.walk():
            ct = deel.get_content_type()
            if ct == "text/plain":
                tekst = _decodeer_payload(deel)
                break
            elif ct == "text/html" and not tekst:
                html = _decodeer_payload(deel)
                tekst = re.sub(r"<[^>]+>", " ", html)
                tekst = re.sub(r"\s+", " ", tekst).strip()
    else:
        ct = msg.get_content_type()
        tekst = _decodeer_payload(msg)
        if ct == "text/html":
            tekst = re.sub(r"<[^>]+>", " ", tekst)
            tekst = re.sub(r"\s+", " ", tekst).strip()
    return tekst


def _decodeer_payload(deel) -> str:
    payload = deel.get_payload(decode=True)
    if not payload:
        return ""
    charset = deel.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _decodeer_header(waarde: str) -> str:
    onderdelen = email.header.decode_header(waarde)
    resultaat = []
    for tekst, charset in onderdelen:
        if isinstance(tekst, bytes):
            resultaat.append(tekst.decode(charset or "utf-8", errors="replace"))
        else:
            resultaat.append(tekst)
    return "".join(resultaat)


def verstuur_briefing_email(onderwerp: str, html_body: str, aan_email: str = None):
    """
    Stuur de dagelijkse briefing als HTML e-mail via Gmail SMTP.

    Args:
        onderwerp: Onderwerpregel van de mail
        html_body: De volledige HTML briefing als body
        aan_email: Ontvanger (standaard: MENTOR_EMAIL uit config)
    """
    aan = aan_email or MENTOR_EMAIL

    bericht = MIMEMultipart("alternative")
    bericht["Subject"] = onderwerp
    bericht["From"] = GMAIL_EMAIL
    bericht["To"] = aan
    bericht.attach(MIMEText(html_body, "html", "utf-8"))

    print(f"  Briefing e-mail versturen naar {aan}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_EMAIL, [aan], bericht.as_string())
    print("  Briefing e-mail verstuurd.")
