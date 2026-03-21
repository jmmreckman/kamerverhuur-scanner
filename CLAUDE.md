# Project: Mentor AI Assistent

Persoonlijk AI-systeem voor Jurian Reckman, mentor en docent aan RS College (vsvonh).

## Wat is dit?

Een dagelijkse briefing-tool die elke ochtend om 07:00 automatisch draait en:

1. **Magister** uitleest — berichten, absenties, leerlingdocumenten
2. **Gmail** uitleest — doorgestuurde Outlook-mails van werk
3. **Google Calendar** uitleest — agenda komende 7 dagen
4. **Claude AI** gebruikt — koppelt berichten aan leerlingen, vat samen, schrijft conceptreacties in Jurians schrijfstijl
5. **Briefing-email** stuurt — overzichtelijke HTML mail naar jmreckman@rscollege.nl

## Gebruiker

- **Naam:** Jurian Reckman
- **Email werk:** jmreckman@rscollege.nl
- **Email privé/Gmail:** jurian28@gmail.com
- **School:** RS College, Magister URL: vsvonh.magister.net
- **Schrijfstijl:** Warm, persoonlijk maar professioneel. Voornaam ouder. Korte zinnen. Jij/je tenzij ouder formeel is.

## Technische opzet

- **Taal:** Python 3.11+
- **AI:** Claude API (claude-sonnet-4-6), sleutel via .env
- **Magister auth:** OAuth2 PKCE via Microsoft SSO (token opgeslagen in `data/magister_token.json`)
- **Outlook:** Niet direct via Graph API — school blokkeert dit. Oplossing: Outlook stuurt mails door naar Gmail, systeem leest Gmail via IMAP
- **Google Calendar:** OAuth2 via `data/google_credentials.json`
- **Database:** SQLite lokaal (`data/mentor.db`) — leerlingen, contacten, berichten

## Bestandsstructuur

```
kamerverhuur-scanner/          ← projectmap (naam is historisch, inhoud is mentor-assistent)
├── CLAUDE.md                  ← dit bestand
├── mentor_assistant/
│   ├── config.py              ← instellingen (privé keys via .env)
│   ├── database.py            ← SQLite helpers
│   ├── sync.py                ← dagelijkse orchestrator
│   ├── ai_verwerker.py        ← Claude AI integratie
│   ├── connectors/
│   │   ├── gmail_imap.py      ← Gmail IMAP (vervangt directe Outlook koppeling)
│   │   ├── outlook_teams.py   ← (oud, niet meer in gebruik)
│   │   ├── magister.py        ← Magister OAuth2 PKCE
│   │   ├── google_calendar.py ← Google Calendar
│   │   └── pdf_verwerker.py   ← PDF extractie uit Magister documenten
│   ├── reports/
│   │   └── html_rapport.py    ← HTML briefing generator
│   └── data/                  ← lokaal, niet in git (.gitignore)
├── installeer_windows.bat
├── start_sync.bat
└── requirements.txt
```

## Belangrijke keuzes / geschiedenis

- **Directe Outlook Graph API werkte niet** — school (rscollege.nl / vsvonh) blokkeert externe app-registraties. Opgelost door Outlook door te sturen naar Gmail en dat via IMAP te lezen.
- **Magister wachtwoord-login werkte niet** — Magister gebruikt Microsoft SSO. Opgelost met OAuth2 PKCE flow via accounts.magister.net, met m6loapp:// redirect URI.
- **Projectnaam 'kamerverhuur-scanner'** is historisch — het project is omgebouwd tot mentor-assistent.

## Huidige status (maart 2026)

Systeem is gebouwd en grotendeels werkend. Nog te testen / instellen:
- Leerlingen toevoegen aan de database
- Eerste volledige sync draaien en briefing-email controleren
- Windows Taakplanner instellen voor automatische dagelijkse sync

## Hoe verder te helpen

Als ik (Claude) context kwijt ben: lees dit bestand opnieuw (`Read CLAUDE.md`).
Jurian hoeft niet elke keer opnieuw uit te leggen wat het systeem doet.
