"""
Configuratie voor Mentor AI Assistent.
Pas alle waarden hieronder aan naar jouw situatie.

Privé keys (API keys, wachtwoorden) worden geladen uit .env in de projectroot.
Maak eenmalig een .env bestand aan — dit wordt nooit gecommit naar git.

STAP 1 t/m 5 moeten ingevuld zijn voordat je het systeem kunt draaien.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Laad .env uit de projectroot (één map boven deze map)
_env_pad = Path(__file__).parent.parent / ".env"
load_dotenv(_env_pad)

# ─────────────────────────────────────────────────────────────────────────────
# STAP 1: Persoonlijke gegevens
# ─────────────────────────────────────────────────────────────────────────────

MENTOR_NAAM = "Jurian"
MENTOR_EMAIL = "jmreckman@rscollege.nl"

# Beschrijf jouw schrijfstijl in emails naar ouders.
# Hoe meer detail, hoe beter de AI-conceptmails worden.
MENTOR_SCHRIJFSTIJL = """
Warm en persoonlijk maar professioneel. Directe aanspreking met voornaam ouder.
Korte, heldere zinnen. Geen jargon. Empathisch bij problemen.
Altijd afsluiten met aanbod voor verdere bespreking.
Gebruik 'jij/je' i.p.v. 'u' tenzij ouder formeel is.
Handtekening: [MENTOR_NAAM], mentor [KLAS] en docent RS College
"""

# ─────────────────────────────────────────────────────────────────────────────
# STAP 2: Claude API (via https://console.anthropic.com)
#
# Je Claude Pro abonnement geeft GEEN API toegang.
# API is apart betaald, maar heel betaalbaar:
#   - Claude Sonnet: ~$3 per miljoen input tokens
#   - Dagelijkse sync kost ~$0.05-0.20 per dag afhankelijk van hoeveel data
#
# Maak een API key aan via: console.anthropic.com → API Keys → Create Key
# ─────────────────────────────────────────────────────────────────────────────

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "JOUW_CLAUDE_API_KEY_HIER")

# Model keuze: claude-sonnet-4-6 is beste balans prijs/kwaliteit.
# Voor extra complexe taken kun je claude-opus-4-6 gebruiken (duurder).
CLAUDE_MODEL = "claude-sonnet-4-6"

# ─────────────────────────────────────────────────────────────────────────────
# STAP 3: Gmail (voor inlezen doorgestuurde mails + versturen briefing)
#
# Vereisten:
#   1. Gmail account aangemaakt (bijv. jurian28@gmail.com)
#   2. 2-stapsverificatie aan: myaccount.google.com → Beveiliging
#   3. App-wachtwoord gegenereerd: myaccount.google.com/apppasswords
#   4. Werk-Outlook stuurt mails door naar dit Gmail adres
# ─────────────────────────────────────────────────────────────────────────────

GMAIL_EMAIL = os.getenv("GMAIL_EMAIL", "jurian28@gmail.com")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# ─────────────────────────────────────────────────────────────────────────────
# Microsoft Azure (niet meer nodig, bewaard voor referentie)
# ─────────────────────────────────────────────────────────────────────────────

GRAPH_CLIENT_ID = "NIET_GEBRUIKT"
GRAPH_CLIENT_SECRET = "NIET_GEBRUIKT"
GRAPH_TENANT_ID = "NIET_GEBRUIKT"

# ─────────────────────────────────────────────────────────────────────────────
# STAP 4: Magister
#
# Geen apart wachtwoord nodig — Magister gebruikt je school Microsoft account.
#
# Eerste keer inloggen:
#   python -m mentor_assistant.connectors.magister
#   → Browser opent automatisch → log in met je rscollege.nl account
#   → Token wordt opgeslagen, daarna volledig automatisch
#
# Token bestand: mentor_assistant/data/magister_token.json
# ─────────────────────────────────────────────────────────────────────────────

MAGISTER_SCHOOL_URL = "https://vsvonh.magister.net"
MAGISTER_USERNAME   = MENTOR_EMAIL                       # login_hint voor Microsoft SSO

# ─────────────────────────────────────────────────────────────────────────────
# STAP 5: Google Calendar
# Zet credentials.json (gedownload van console.cloud.google.com) in:
#   mentor_assistant/data/google_credentials.json
# ─────────────────────────────────────────────────────────────────────────────
# (geen extra instelling nodig hier)

# ─────────────────────────────────────────────────────────────────────────────
# Optioneel: tijdstip dagelijkse sync
# ─────────────────────────────────────────────────────────────────────────────

SYNC_TIJD = "07:00"   # HH:MM — wanneer de ochtend-sync draait
