"""
Microsoft Graph API connector voor Outlook e-mail en Teams berichten.

Setup (eenmalig):
  1. Ga naar portal.azure.com → Azure Active Directory → App registrations
  2. "New registration" → geef naam "MentorAssistent"
  3. Redirect URI: http://localhost:8080
  4. Na aanmaken: noteer Application (client) ID en Directory (tenant) ID
  5. Certificates & secrets → New client secret → kopieer de waarde
  6. API permissions → Add permission → Microsoft Graph → Delegated:
       Mail.Read, Mail.ReadWrite, Chat.Read, ChannelMessage.Read.All, Calendars.Read
  7. Vul de waarden in in config.py

Documentatie: https://learn.microsoft.com/en-us/graph/overview
"""
import json
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from ..config import GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET, GRAPH_TENANT_ID
from ..database import get_sync_status, sla_communicatie_op, update_sync_log

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_FILE = Path(__file__).parent.parent / "data" / "ms_token.json"
SCOPE = " ".join([
    "Mail.Read",
    "Mail.ReadWrite",
    "Chat.Read",
    "ChannelMessage.Read.All",
    "offline_access",
])


# ── OAuth token beheer ────────────────────────────────────────────────────────

def _laad_token() -> dict | None:
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def _sla_token_op(token: dict):
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(token, indent=2))


def _vernieuw_token(token: dict) -> dict:
    resp = requests.post(
        f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": GRAPH_CLIENT_ID,
            "client_secret": GRAPH_CLIENT_SECRET,
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
            "scope": SCOPE,
        },
        timeout=30,
    )
    resp.raise_for_status()
    nieuw = resp.json()
    nieuw.setdefault("refresh_token", token["refresh_token"])
    nieuw["expires_at"] = time.time() + nieuw.get("expires_in", 3600)
    _sla_token_op(nieuw)
    return nieuw


def _is_verlopen(token: dict) -> bool:
    return time.time() >= token.get("expires_at", 0) - 60


def get_access_token() -> str:
    """Geef een geldig access token terug. Vraagt eenmalig om login als nodig."""
    token = _laad_token()

    if token and not _is_verlopen(token):
        return token["access_token"]

    if token and token.get("refresh_token"):
        token = _vernieuw_token(token)
        return token["access_token"]

    # Eerste keer: browser-gebaseerde login
    return _doe_oauth_flow()


def _doe_oauth_flow() -> str:
    """Voer OAuth authorization code flow uit via lokale server."""
    auth_code_container = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            params = parse_qs(urlparse(self.path).query)
            if "code" in params:
                auth_code_container["code"] = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Ingelogd! Sluit dit venster.</h2></body></html>")

        def log_message(self, format, *args):
            pass  # onderdruk server logs

    server = HTTPServer(("localhost", 8080), Handler)
    server.timeout = 120

    params = urlencode({
        "client_id": GRAPH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": "http://localhost:8080",
        "scope": SCOPE,
        "response_mode": "query",
    })
    url = f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}/oauth2/v2.0/authorize?{params}"

    print(f"\nOpenen van browser voor Microsoft login...\n{url}\n")
    webbrowser.open(url)

    server.handle_request()

    if "code" not in auth_code_container:
        raise RuntimeError("Geen authorization code ontvangen van Microsoft.")

    resp = requests.post(
        f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": GRAPH_CLIENT_ID,
            "client_secret": GRAPH_CLIENT_SECRET,
            "code": auth_code_container["code"],
            "redirect_uri": "http://localhost:8080",
            "grant_type": "authorization_code",
            "scope": SCOPE,
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json()
    token["expires_at"] = time.time() + token.get("expires_in", 3600)
    _sla_token_op(token)
    print("Microsoft token opgeslagen.")
    return token["access_token"]


# ── Graph API hulpfunctie ────────────────────────────────────────────────────

def _graph_get(url: str, params: dict = None) -> dict:
    headers = {"Authorization": f"Bearer {get_access_token()}"}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Outlook mails synchroniseren ─────────────────────────────────────────────

def sync_outlook():
    """
    Haal nieuwe mails op uit Outlook Inbox.
    Gebruikt delta-queries voor incremental sync (alleen nieuwe mails).
    Slaat inkomende mails op in de database.
    Retourneert aantal nieuwe berichten.
    """
    print("Synchroniseren Outlook mails...")
    sync_status = get_sync_status("outlook")
    delta_link = sync_status["laatste_item_id"] if sync_status else None

    try:
        if delta_link:
            url = delta_link
        else:
            # Eerste sync: haal mails van afgelopen 30 dagen
            sinds = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            url = (
                f"{GRAPH_BASE}/me/mailFolders/inbox/messages/delta"
                f"?$filter=receivedDateTime ge {sinds}"
                f"&$select=id,subject,from,toRecipients,body,receivedDateTime,isRead"
                f"&$top=50"
            )

        nieuwe_mails = 0
        nieuwe_delta_link = None

        while url:
            data = _graph_get(url)
            for mail in data.get("value", []):
                _verwerk_outlook_mail(mail)
                nieuwe_mails += 1

            nieuwe_delta_link = data.get("@odata.deltaLink")
            url = data.get("@odata.nextLink")

        update_sync_log("outlook", laatste_item_id=nieuwe_delta_link)
        print(f"  → {nieuwe_mails} nieuwe mail(s) opgeslagen.")
        return nieuwe_mails

    except Exception as e:
        update_sync_log("outlook", status="fout", foutmelding=str(e))
        raise


def _verwerk_outlook_mail(mail: dict):
    """Verwerk één Outlook mail naar database record."""
    van = mail.get("from", {}).get("emailAddress", {})
    aan_lijst = mail.get("toRecipients", [])
    aan = "; ".join(
        r.get("emailAddress", {}).get("address", "") for r in aan_lijst
    )
    body = mail.get("body", {}).get("content", "")
    # Verwijder HTML tags voor opslag als platte tekst
    import re
    body_tekst = re.sub(r"<[^>]+>", " ", body).strip()
    body_tekst = re.sub(r"\s+", " ", body_tekst)

    sla_communicatie_op({
        "bron": "outlook",
        "extern_id": mail["id"],
        "richting": "inkomend",
        "van_email": van.get("address"),
        "aan_email": aan,
        "onderwerp": mail.get("subject"),
        "inhoud": body_tekst[:10000],  # max 10k tekens
        "datum": mail.get("receivedDateTime", datetime.now().isoformat()),
    })


# ── Teams berichten synchroniseren ───────────────────────────────────────────

def sync_teams():
    """
    Haal recente Teams chat berichten op.
    Let op: ChannelMessage.Read.All vereist admin consent in grotere organisaties.
    """
    print("Synchroniseren Teams berichten...")
    try:
        chats_data = _graph_get(f"{GRAPH_BASE}/me/chats?$top=20")
        nieuwe_berichten = 0

        for chat in chats_data.get("value", []):
            chat_id = chat["id"]
            msgs_data = _graph_get(
                f"{GRAPH_BASE}/me/chats/{chat_id}/messages?$top=10"
            )
            for msg in msgs_data.get("value", []):
                if msg.get("messageType") != "message":
                    continue
                sender = msg.get("from", {}).get("user", {})
                body = msg.get("body", {}).get("content", "")
                import re
                body_tekst = re.sub(r"<[^>]+>", " ", body).strip()

                sla_communicatie_op({
                    "bron": "teams",
                    "extern_id": msg["id"],
                    "richting": "inkomend",
                    "van_email": sender.get("displayName"),
                    "aan_email": "teams_chat",
                    "onderwerp": f"Teams: {chat.get('topic', 'Direct bericht')}",
                    "inhoud": body_tekst[:5000],
                    "datum": msg.get("createdDateTime", datetime.now().isoformat()),
                })
                nieuwe_berichten += 1

        update_sync_log("teams")
        print(f"  → {nieuwe_berichten} Teams bericht(en) opgeslagen.")
        return nieuwe_berichten

    except Exception as e:
        update_sync_log("teams", status="fout", foutmelding=str(e))
        print(f"  ⚠ Teams sync mislukt: {e}")
        return 0
