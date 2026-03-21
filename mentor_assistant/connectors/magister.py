"""
Magister connector via OAuth2 PKCE + accounts.magister.net.

Magister gebruikt Microsoft SSO voor scholen die met werk-accounts inloggen.
Het authenticatiepad:
  1. accounts.magister.net  (Magister eigen OIDC server, PKCE)
  2. login.microsoftonline.com  (school Microsoft SSO)
  3. Terug naar accounts.magister.net  → Magister access token

Eenmalige login:
  - python -m mentor_assistant.connectors.magister  (of via sync.py)
  - Browser opent automatisch → log in met rscollege.nl Microsoft account
  - Token wordt opgeslagen in data/magister_token.json
  - Daarna volledig automatisch (refresh token zorgt voor hernieuwing)

Setup in config.py:
  MAGISTER_SCHOOL_URL  = "https://rscollege.magister.net"
  MAGISTER_USERNAME    = "jmreckman@rscollege.nl"   # login_hint voor Microsoft
"""

import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from ..config import MAGISTER_SCHOOL_URL, MAGISTER_USERNAME
from ..database import get_connection, sla_communicatie_op, update_sync_log

# ── OAuth constanten ───────────────────────────────────────────────────────────

ACCOUNTS_BASE     = "https://accounts.magister.net"
AUTH_ENDPOINT     = f"{ACCOUNTS_BASE}/connect/authorize"
TOKEN_ENDPOINT    = f"{ACCOUNTS_BASE}/connect/token"

# M6LOAPP is de publieke Magister app-client (geen secret nodig, ondersteunt PKCE)
MAGISTER_CLIENT_ID = "M6LOAPP"
MAGISTER_SCOPES    = "openid profile offline_access"
REDIRECT_PORT      = 8765
REDIRECT_URI       = "m6loapp://oauth/callback"

TOKEN_PAD = Path(__file__).parent.parent / "data" / "magister_token.json"
DOCS_DIR  = Path(__file__).parent.parent / "data" / "magister_docs"


# ── PKCE helpers ───────────────────────────────────────────────────────────────

def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ── Lokale callback server ─────────────────────────────────────────────────────

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            _CallbackHandler.code = params["code"][0]
            body = b"<html><body><h2>Ingelogd! Sluit dit venster.</h2></body></html>"
        elif "error" in params:
            _CallbackHandler.error = params.get("error_description", params["error"])[0]
            body = b"<html><body><h2>Login mislukt. Controleer de foutmelding in de terminal.</h2></body></html>"
        else:
            body = b"Wachten..."
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass  # onderdruk server logs


def _wacht_op_callback(timeout: int = 120) -> str:
    """Start lokale server, wacht op OAuth callback, geef auth code terug."""
    _CallbackHandler.code = None
    _CallbackHandler.error = None

    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    server.timeout = 2

    deadline = time.time() + timeout
    while time.time() < deadline:
        server.handle_request()
        if _CallbackHandler.code:
            server.server_close()
            return _CallbackHandler.code
        if _CallbackHandler.error:
            server.server_close()
            raise RuntimeError(f"OAuth fout: {_CallbackHandler.error}")

    server.server_close()
    raise TimeoutError("Geen inlog ontvangen binnen 2 minuten.")


# ── Token opslaan / laden ──────────────────────────────────────────────────────

def _sla_token_op(token_data: dict):
    TOKEN_PAD.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PAD.write_text(json.dumps(token_data, indent=2))


def _laad_token() -> dict | None:
    if not TOKEN_PAD.exists():
        return None
    try:
        return json.loads(TOKEN_PAD.read_text())
    except Exception:
        return None


def _ververs_token(token: dict) -> dict:
    """Gebruik refresh_token om nieuw access_token te halen."""
    resp = requests.post(TOKEN_ENDPOINT, data={
        "grant_type":    "refresh_token",
        "refresh_token": token["refresh_token"],
        "client_id":     MAGISTER_CLIENT_ID,
    }, timeout=15)
    resp.raise_for_status()
    nieuw = resp.json()
    # Bewaar refresh_token als de nieuwe response hem niet teruggeeft
    if "refresh_token" not in nieuw:
        nieuw["refresh_token"] = token["refresh_token"]
    nieuw["expires_at"] = time.time() + nieuw.get("expires_in", 3600) - 60
    _sla_token_op(nieuw)
    return nieuw


# ── Volledige OAuth PKCE login ─────────────────────────────────────────────────

def login_magister() -> dict:
    """
    Voer eenmalige OAuth PKCE login uit via browser.
    Geeft token dict terug (bevat access_token en refresh_token).
    """
    verifier   = _pkce_verifier()
    challenge  = _pkce_challenge(verifier)
    state      = secrets.token_urlsafe(16)

    params = {
        "client_id":             MAGISTER_CLIENT_ID,
        "response_type":         "code",
        "scope":                 MAGISTER_SCOPES,
        "redirect_uri":          REDIRECT_URI,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
        "state":                 state,
        "login_hint":            MAGISTER_USERNAME,  # triggert direct Microsoft SSO
    }
    auth_url = f"{AUTH_ENDPOINT}?{urlencode(params)}"

    print(f"\nMagister OAuth login:")
    print(f"  Browser opent automatisch. Log in met je {MAGISTER_USERNAME} account.")
    print(f"  Na het inloggen probeert de browser een 'm6loapp://...' pagina te openen.")
    print(f"  Die pagina kan niet worden geopend — dat is normaal.")
    print(f"  Kopieer dan de volledige URL uit de adresbalk en plak hem hieronder.\n")

    webbrowser.open(auth_url)
    callback_url = input("  Plak hier de volledige m6loapp://... URL: ").strip()
    params = parse_qs(urlparse(callback_url).query)
    if "error" in params:
        raise RuntimeError(f"OAuth fout: {params.get('error_description', params['error'])[0]}")
    if "code" not in params:
        raise RuntimeError("Geen autorisatiecode gevonden in de URL.")
    code = params["code"][0]

    # Wissel code in voor token
    resp = requests.post(TOKEN_ENDPOINT, data={
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
        "client_id":     MAGISTER_CLIENT_ID,
        "code_verifier": verifier,
    }, timeout=15)
    resp.raise_for_status()

    token = resp.json()
    token["expires_at"] = time.time() + token.get("expires_in", 3600) - 60
    _sla_token_op(token)
    print("  Magister token opgeslagen. Volgende keer automatisch.")
    return token


def get_token() -> str:
    """Geef geldig access_token terug; login als nodig, ververs als verlopen."""
    token = _laad_token()

    if token is None:
        print("Geen Magister token gevonden — eerste login vereist.")
        token = login_magister()
    elif time.time() > token.get("expires_at", 0):
        print("Magister token verlopen, verversen...")
        try:
            token = _ververs_token(token)
        except Exception as e:
            print(f"  Verversing mislukt ({e}), opnieuw inloggen...")
            token = login_magister()

    return token["access_token"]


# ── Magister API client ────────────────────────────────────────────────────────

class MagisterClient:
    """Bearer-token gebaseerde Magister API client."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MentorAssistent/1.0"})
        self.base = MAGISTER_SCHOOL_URL.rstrip("/")
        self._token: str | None = None

    def _auth_header(self) -> dict:
        if not self._token:
            self._token = get_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, pad: str, **kwargs) -> dict | list:
        resp = self.session.get(
            f"{self.base}{pad}",
            headers=self._auth_header(),
            timeout=20,
            **kwargs,
        )
        if resp.status_code == 401:
            # Token mogelijk verlopen; forceer refresh en probeer opnieuw
            token_data = _laad_token()
            if token_data and token_data.get("refresh_token"):
                token_data = _ververs_token(token_data)
                self._token = token_data["access_token"]
                resp = self.session.get(
                    f"{self.base}{pad}",
                    headers=self._auth_header(),
                    timeout=20,
                    **kwargs,
                )
        resp.raise_for_status()
        return resp.json()

    def get_account_info(self) -> dict:
        return self._get("/api/account?noCache=true")

    def get_leerlingen(self) -> list[dict]:
        account = self.get_account_info()
        persoon_id = account.get("Persoon", {}).get("Id")
        if not persoon_id:
            raise RuntimeError("Kan persoon ID niet ophalen uit Magister account.")
        leerlingen = self._get(f"/api/personen/{persoon_id}/leerlingen")
        return leerlingen.get("Items", leerlingen) if isinstance(leerlingen, dict) else leerlingen

    def get_berichten(self, map_naam: str = "inbox", limiet: int = 20) -> list[dict]:
        berichten = self._get(f"/api/berichten?map={map_naam}&top={limiet}")
        return berichten.get("items", berichten) if isinstance(berichten, dict) else berichten

    def get_bericht_detail(self, bericht_id: int) -> dict:
        return self._get(f"/api/berichten/{bericht_id}")

    def get_studiewijzer_documenten(self, leerling_id: int) -> list[dict]:
        try:
            docs = self._get(f"/api/leerlingen/{leerling_id}/documenten?top=50")
            return docs.get("Items", docs) if isinstance(docs, dict) else docs
        except Exception:
            return []

    def get_absenties(self, leerling_id: int, dagen: int = 30) -> list[dict]:
        tot = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        van = (datetime.now() - timedelta(days=dagen)).strftime("%Y-%m-%dT%H:%M:%S")
        try:
            data = self._get(
                f"/api/leerlingen/{leerling_id}/absenties",
                params={"van": van, "tot": tot, "top": 100},
            )
            return data.get("Items", data) if isinstance(data, dict) else data
        except Exception:
            return []

    def download_document(self, document_url: str, pad: Path) -> bool:
        try:
            resp = self.session.get(
                f"{self.base}{document_url}" if document_url.startswith("/") else document_url,
                headers=self._auth_header(),
                timeout=30,
                stream=True,
            )
            resp.raise_for_status()
            pad.parent.mkdir(parents=True, exist_ok=True)
            pad.write_bytes(resp.content)
            return True
        except Exception as e:
            print(f"  ⚠ Download mislukt {document_url}: {e}")
            return False


# ── Sync functie ───────────────────────────────────────────────────────────────

def sync_magister():
    """
    Synchroniseer Magister data:
    - Nieuwe berichten uit berichtencentrum
    - Documenten per mentorleerling
    - Absenties per mentorleerling

    Bij eerste gebruik opent automatisch een browser voor eenmalige login.
    """
    print("Synchroniseren Magister...")
    try:
        client = MagisterClient()

        # Valideer verbinding
        client.get_account_info()
        print("  Magister: verbonden.")

        _sync_magister_berichten(client)
        _sync_leerling_data(client)

        update_sync_log("magister")
        print("  → Magister sync compleet.")

    except Exception as e:
        update_sync_log("magister", status="fout", foutmelding=str(e))
        print(f"  ⚠ Magister sync mislukt: {e}")
        raise


def _sync_magister_berichten(client: MagisterClient):
    berichten = client.get_berichten(limiet=30)
    nieuw = 0
    for bericht in berichten:
        bericht_id = bericht.get("Id") or bericht.get("id")
        if not bericht_id:
            continue
        try:
            detail = client.get_bericht_detail(bericht_id)
        except Exception:
            detail = bericht

        inhoud = detail.get("Tekst") or detail.get("tekst") or ""
        inhoud = re.sub(r"<[^>]+>", " ", inhoud).strip()
        inhoud = re.sub(r"\s+", " ", inhoud)

        afzender = detail.get("Afzender", {}) or {}

        sla_communicatie_op({
            "bron":       "magister",
            "extern_id":  f"mag_{bericht_id}",
            "richting":   "inkomend",
            "van_email":  afzender.get("Naam") or afzender.get("naam"),
            "aan_email":  "mentor",
            "onderwerp":  detail.get("Onderwerp") or detail.get("onderwerp"),
            "inhoud":     inhoud[:8000],
            "datum":      detail.get("VerstuurdOp") or detail.get("verstuurdOp")
                          or datetime.now().isoformat(),
        })
        nieuw += 1

    print(f"  → {nieuw} Magister bericht(en) verwerkt.")


def _sync_leerling_data(client: MagisterClient):
    conn = get_connection()
    leerlingen = conn.execute(
        "SELECT id, magister_id, voornaam, achternaam FROM leerlingen WHERE magister_id IS NOT NULL"
    ).fetchall()
    conn.close()

    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    for leerling in leerlingen:
        leerling_id = leerling["id"]
        magister_id = int(leerling["magister_id"])
        naam = f"{leerling['voornaam']} {leerling['achternaam']}"

        try:
            docs = client.get_studiewijzer_documenten(magister_id)
            _verwerk_documenten(client, docs, leerling_id, naam)
        except Exception as e:
            print(f"  ⚠ Documenten {naam}: {e}")

        try:
            absenties = client.get_absenties(magister_id)
            _verwerk_absenties(absenties, leerling_id, naam)
        except Exception as e:
            print(f"  ⚠ Absenties {naam}: {e}")


def _verwerk_documenten(client: MagisterClient, docs: list, leerling_id: int, naam: str):
    conn = get_connection()
    nieuw = 0
    for doc in docs:
        doc_id = doc.get("Id") or doc.get("id")
        bestandsnaam = doc.get("Naam") or doc.get("naam") or f"document_{doc_id}"
        if not bestandsnaam.lower().endswith(".pdf"):
            bestandsnaam += ".pdf"

        bestaand = conn.execute(
            "SELECT id FROM documenten WHERE leerling_id = ? AND bestandsnaam = ?",
            (leerling_id, bestandsnaam)
        ).fetchone()
        if bestaand:
            continue

        lokaal_pad = DOCS_DIR / str(leerling_id) / bestandsnaam
        download_url = doc.get("Url") or doc.get("url") or ""
        if download_url:
            client.download_document(download_url, lokaal_pad)

        conn.execute("""
            INSERT INTO documenten (leerling_id, bestandsnaam, lokaal_pad, bron, datum_document)
            VALUES (?, ?, ?, 'magister', ?)
        """, (
            leerling_id,
            bestandsnaam,
            str(lokaal_pad) if lokaal_pad.exists() else None,
            doc.get("Datum") or doc.get("datum"),
        ))
        nieuw += 1

    conn.commit()
    conn.close()
    if nieuw:
        print(f"  → {nieuw} nieuw(e) document(en) voor {naam}.")


def _verwerk_absenties(absenties: list, leerling_id: int, naam: str):
    if not absenties:
        return
    conn = get_connection()
    nieuw = 0
    for abs_ in absenties:
        abs_id = abs_.get("Id") or abs_.get("id")
        if not abs_id:
            continue
        bestaand = conn.execute(
            "SELECT id FROM tijdlijn WHERE leerling_id = ? AND type = 'absentie' AND beschrijving LIKE ?",
            (leerling_id, f"%{abs_id}%")
        ).fetchone()
        if bestaand:
            continue

        reden = abs_.get("Omschrijving") or abs_.get("omschrijving") or "onbekend"
        datum = abs_.get("Begin") or abs_.get("begin") or datetime.now().isoformat()

        conn.execute("""
            INSERT INTO tijdlijn (leerling_id, datum, type, titel, beschrijving, aangemaakt_door)
            VALUES (?, ?, 'absentie', ?, ?, 'systeem')
        """, (
            leerling_id,
            datum[:10],
            f"Absentie: {reden}",
            f"Magister absentie ID {abs_id}: {reden}",
        ))
        nieuw += 1

    conn.commit()
    conn.close()
    if nieuw:
        print(f"  → {nieuw} absentie(s) voor {naam} in tijdlijn.")


# ── Standalone login commando ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("Magister eenmalige login")
    print("=" * 40)
    token = login_magister()
    print(f"\nSucces! Token geldig tot: {datetime.fromtimestamp(token['expires_at'])}")
    print("Je kunt dit venster sluiten.")
