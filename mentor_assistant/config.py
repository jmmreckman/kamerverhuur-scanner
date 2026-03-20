"""
Configuratie voor Mentor AI Assistent.
Pas alle waarden hieronder aan naar jouw situatie.

STAP 1 t/m 5 moeten ingevuld zijn voordat je het systeem kunt draaien.
"""

# ─────────────────────────────────────────────────────────────────────────────
# STAP 1: Persoonlijke gegevens
# ─────────────────────────────────────────────────────────────────────────────

MENTOR_NAAM = "jouw voornaam"   # bijv. "Jan"
MENTOR_EMAIL = "jouw.naam@rscollege.nl"

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
# STAP 2: Gemini API (gratis via https://aistudio.google.com/app/apikey)
# ─────────────────────────────────────────────────────────────────────────────

GEMINI_API_KEY = "JOUW_GEMINI_API_KEY_HIER"

# ─────────────────────────────────────────────────────────────────────────────
# STAP 3: Microsoft Azure App Registration (voor Outlook + Teams)
# Instructies: zie mentor_assistant/connectors/outlook_teams.py bovenaan
# ─────────────────────────────────────────────────────────────────────────────

GRAPH_CLIENT_ID = "JOUW_AZURE_CLIENT_ID"
GRAPH_CLIENT_SECRET = "JOUW_AZURE_CLIENT_SECRET"
GRAPH_TENANT_ID = "JOUW_AZURE_TENANT_ID"   # of "common" als niet zeker

# ─────────────────────────────────────────────────────────────────────────────
# STAP 4: Magister
# ─────────────────────────────────────────────────────────────────────────────

MAGISTER_SCHOOL_URL = "https://rscollege.magister.net"   # pas aan als nodig
MAGISTER_USERNAME = MENTOR_EMAIL
MAGISTER_PASSWORD = "JOUW_MAGISTER_WACHTWOORD"

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
