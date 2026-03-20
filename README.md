# Mentor AI Assistent

Persoonlijk AI-systeem voor mentoren op het voortgezet onderwijs.
Synchroniseert dagelijks Outlook, Teams, Magister en Google Calendar.
Stuurt elke ochtend een briefing-email met AI-samenvattingen en conceptreacties.

Gebruikt **Claude** (Anthropic) voor alle AI-verwerking — het 200k token
contextvenster is ideaal voor leerlingen met veel documenten en communicatie.

---

## Wat doet het?

Elke ochtend om 07:00 draait automatisch een script dat:

1. **Outlook** — haalt nieuwe e-mails op
2. **Teams** — haalt nieuwe berichten op
3. **Magister** — haalt berichten, absenties en leerlingdocumenten op
4. **Google Calendar** — haalt agenda van de komende 7 dagen op
5. **PDF documenten** — extraheert tekst uit Magister-documenten
6. **Claude AI** — koppelt berichten aan leerlingen, vat samen, schrijft conceptreacties
7. **Briefing e-mail** — stuurt een overzichtelijke HTML mail naar je werkmail

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

### Claude API
De API is apart van je Claude Pro abonnement, maar heel betaalbaar (~5-20 cent per dag).
1. Ga naar console.anthropic.com
2. Maak account aan en voeg betaalmethode toe
3. "API Keys" → "Create Key"
4. Kopieer naar `config.py`: `CLAUDE_API_KEY = "sk-ant-..."`

### Microsoft Azure (voor Outlook + Teams + email versturen)

> Tip: vraag je school-ICT om hulp als je hier niet uitkomt.

1. portal.azure.com → "App registrations" → "New registration"
2. Naam: `MentorAssistent`, Redirect URI: `http://localhost:8080`
3. Kopieer **Application (client) ID** en **Directory (tenant) ID**
4. "Certificates & secrets" → "New client secret" → kopieer de **Value**
5. "API permissions" → "Microsoft Graph" → "Delegated":
   `Mail.Read`, `Mail.ReadWrite`, `Mail.Send`, `Chat.Read`, `offline_access`
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
│   ├── ai_verwerker.py        <- Claude AI integratie
│   ├── connectors/
│   │   ├── outlook_teams.py   <- Microsoft Graph + email verzenden
│   │   ├── magister.py        <- Magister
│   │   ├── google_calendar.py <- Google Calendar
│   │   └── pdf_verwerker.py   <- PDF extractie
│   ├── reports/
│   │   └── html_rapport.py    <- HTML briefing generator
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
| Email versturen mislukt | Controleer dat `Mail.Send` permissie is toegevoegd in Azure |
| Magister login mislukt | Controleer URL en wachtwoord in config.py |
| Google Calendar mislukt | Verwijder `data/google_token.json` en run opnieuw |
| Claude fout | Controleer API key en saldo op console.anthropic.com |
| Geen email ontvangen | Check spam/junk folder. Briefing staat ook lokaal in `data/rapporten/` |
