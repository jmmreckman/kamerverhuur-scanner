"""
Google Calendar connector.

Setup (eenmalig):
  1. Ga naar console.cloud.google.com
  2. Maak project "MentorAssistent"
  3. Activeer Google Calendar API
  4. Maak OAuth 2.0 credentials aan (Desktop App)
  5. Download credentials.json → zet in mentor_assistant/data/
  6. Run dit script eenmalig handmatig: python -m mentor_assistant.connectors.google_calendar
     → browser opent voor toestemming, token wordt opgeslagen

Vereiste pakket: google-auth-oauthlib google-api-python-client
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
CREDENTIALS_FILE = DATA_DIR / "google_credentials.json"
TOKEN_FILE = DATA_DIR / "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _get_service():
    """Bouw Google Calendar service op met opgeslagen of nieuwe credentials."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise ImportError(
            "Installeer: pip install google-auth-oauthlib google-api-python-client"
        )

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Google credentials niet gevonden: {CREDENTIALS_FILE}\n"
                    "Download credentials.json van console.cloud.google.com"
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def sync_google_calendar(dagen_vooruit: int = 7) -> list[dict]:
    """
    Haal agenda-items op voor de komende X dagen.
    Retourneert lijst van events.
    """
    print("Synchroniseren Google Calendar...")
    try:
        service = _get_service()

        nu = datetime.now(timezone.utc)
        tot = nu + timedelta(days=dagen_vooruit)

        events_result = service.events().list(
            calendarId="primary",
            timeMin=nu.isoformat(),
            timeMax=tot.isoformat(),
            maxResults=50,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = events_result.get("items", [])
        print(f"  → {len(events)} agenda-item(s) opgehaald.")

        # Sla relevante events op in JSON voor de dagelijkse briefing
        relevant = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            relevant.append({
                "titel": event.get("summary", "(geen titel)"),
                "start": start,
                "eind": event["end"].get("dateTime", event["end"].get("date")),
                "locatie": event.get("location"),
                "beschrijving": event.get("description", "")[:500],
                "deelnemers": [
                    a.get("email") for a in event.get("attendees", [])
                ],
            })

        # Sla op als JSON cache
        cache_bestand = DATA_DIR / "agenda_cache.json"
        cache_bestand.write_text(
            json.dumps(relevant, indent=2, ensure_ascii=False)
        )

        from ..database import update_sync_log
        update_sync_log("google_calendar")
        return relevant

    except Exception as e:
        from ..database import update_sync_log
        update_sync_log("google_calendar", status="fout", foutmelding=str(e))
        print(f"  ⚠ Google Calendar sync mislukt: {e}")
        return []


def get_agenda_vandaag() -> list[dict]:
    """Laad gecachte agenda-items voor vandaag."""
    cache_bestand = DATA_DIR / "agenda_cache.json"
    if not cache_bestand.exists():
        return []
    events = json.loads(cache_bestand.read_text())
    vandaag = datetime.now().strftime("%Y-%m-%d")
    return [e for e in events if e["start"].startswith(vandaag)]


if __name__ == "__main__":
    # Eenmalig uitvoeren voor eerste OAuth flow
    events = sync_google_calendar()
    for e in events:
        print(f"  {e['start'][:16]} - {e['titel']}")
