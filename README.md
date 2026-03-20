# Mentor AI Assistent

Persoonlijk AI-systeem voor mentoren op het voortgezet onderwijs.
Synchroniseert dagelijks Outlook, Teams, Magister en Google Calendar.
Genereert elke ochtend een briefing met conceptreacties op binnenkomende berichten.

---

## Wat doet het?

Elke ochtend om 07:00 draait automatisch een script dat:

1. **Outlook** — haalt nieuwe e-mails op
2. **Teams** — haalt nieuwe berichten op
3. **Magister** — haalt berichten, absenties en leerlingdocumenten op
4. **Google Calendar** — haalt agenda van de komende 7 dagen op
5. **PDF documenten** — extraheert tekst uit Magister-documenten
6. **AI verwerking** — koppelt berichten aan leerlingen, vat samen, maakt conceptreacties
7. **HTML briefing** — opent automatisch in browser

---

## Installatie (Windows, eenmalig)

### Vereisten
- Windows 10/11 met Python 3.11+ ([python.org](https://python.org/downloads) — vink "Add to PATH" aan)
- Internettoegang

### Stap 1: Download en installeer

1. Kopieer de projectmap naar je PC, bijv. `C:\MentorAssistent\`
2. Dubbelklik `installeer_windows.bat`
3. Volg de instructies op het scherm

---

## Configuratie (verplicht)

Open `mentor_assistant/config.py` in Kladblok of Notepad++ en vul in:

### Persoonlijke gegevens
```python
MENTOR_NAAM = "Jan"
MENTOR_EMAIL = "jan.dejong@rscollege.nl"
MENTOR_SCHRIJFSTIJL = "Warm, direct, eerste naam ouder..."
```

### Gemini API (gratis)
1. Ga naar aistudio.google.com/app/apikey
2. Log in met je Google account → klik "Create API key"
3. Kopieer naar `config.py`: `GEMINI_API_KEY = "AIza..."`

### Microsoft Azure (voor Outlook + Teams)

> Tip: vraag je school-ICT om hulp als je hier niet uitkomt.

1. portal.azure.com → "App registrations" → "New registration"
2. Naam: `MentorAssistent`, Redirect URI: `http://localhost:8080`
3. Kopieer **Application (client) ID** en **Directory (tenant) ID**
4. "Certificates & secrets" → "New client secret" → kopieer de **Value**
5. "API permissions" → "Microsoft Graph" → "Delegated":
   `Mail.Read`, `Mail.ReadWrite`, `Chat.Read`, `offline_access`
6. Vul in `config.py`:
```python
GRAPH_CLIENT_ID     = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
GRAPH_CLIENT_SECRET = "jouw~secret~value"
GRAPH_TENANT_ID     = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

### Google Calendar

1. console.cloud.google.com → nieuw project → Google Calendar API inschakelen
2. "Credentials" → "OAuth 2.0 Client ID" → "Desktop app" → download JSON
3. Hernoem naar `google_credentials.json` → zet in `mentor_assistant/data/`

### Magister
```python
MAGISTER_SCHOOL_URL = "https://rscollege.magister.net"
MAGISTER_USERNAME   = "jan.dejong@rscollege.nl"
MAGISTER_PASSWORD   = "jouwwachtwoord"
```

---

## Leerlingen toevoegen

```python
# Voer uit in Python console vanuit de projectmap
import sys
sys.path.insert(0, r"C:\MentorAssistent\kamerverhuur-scanner")

from mentor_assistant.database import get_connection, init_database
init_database()

conn = get_connection()
# Leerling toevoegen
conn.execute("""
    INSERT INTO leerlingen (voornaam, tussenvoegsel, achternaam, klas, leerjaar, magister_id, notities)
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", ("Emma", "van", "Berg", "4A", 4, "12345", "Dyslexieverklaring, begeleiding RT 1x/week"))

# Ouder/contact toevoegen (leerling_id = 1 als eerste leerling)
conn.execute("""
    INSERT INTO contacten (leerling_id, rol, voornaam, achternaam, email, telefoon)
    VALUES (1, 'moeder', 'Petra', 'van Berg', 'p.vberg@gmail.com', '06-12345678')
""")
conn.commit()
conn.close()
```

De `magister_id` vind je in de Magister URL als je een leerling opent.

---

## Handmatig draaien

Dubbelklik `start_sync.bat` of via commandoregel:
```
cd C:\MentorAssistent\kamerverhuur-scanner
python -m mentor_assistant.sync
```

---

## Bestandsstructuur

```
kamerverhuur-scanner/
├── mentor_assistant/
│   ├── config.py              <- HIER jouw gegevens invullen
│   ├── database.py
│   ├── sync.py                <- Dagelijkse orchestrator
│   ├── ai_verwerker.py        <- Gemini AI integratie
│   ├── connectors/
│   │   ├── outlook_teams.py   <- Microsoft Graph
│   │   ├── magister.py        <- Magister
│   │   ├── google_calendar.py <- Google Calendar
│   │   └── pdf_verwerker.py   <- PDF extractie
│   ├── reports/
│   │   └── html_rapport.py    <- HTML briefing
│   └── data/                  <- lokaal, niet in git
├── installeer_windows.bat
├── start_sync.bat
├── requirements.txt
└── README.md
```

---

## Problemen oplossen

| Probleem | Oplossing |
|---------|-----------|
| Outlook sync mislukt | Verwijder `data/ms_token.json` en probeer opnieuw |
| Magister login mislukt | Controleer URL en wachtwoord in config.py |
| Google Calendar mislukt | Verwijder `data/google_token.json` en run opnieuw |
| Gemini fout | Controleer API key. Gratis quotum: 1500 req/dag |
| Briefing opent niet | Open handmatig: `data/rapporten/briefing_DATUM.html` |
