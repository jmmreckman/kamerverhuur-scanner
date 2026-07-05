# kamerverhuur-scanner

Dagelijks (09:00) programma dat nieuwe koopwoningen in Rotterdam scant op kansen
voor kamerverhuur, en een overzicht mailt van de huizen die alle checks
doorstaan.

## Wat het doet

Elke ochtend om 09:00:

1. Leest de nieuwe Funda-listings uit je dagelijkse Funda-zoekopdracht-alert
   (via e-mail, zie hieronder — **geen scraping**, funda blokkeert dat actief).
2. Zoekt elk adres op via de landelijke PDOK-adressenservice (coördinaten + wijk/buurt).
3. Checkt automatisch:
   - **Nul-quotumgebied** — via de officiële GIS-kaartlaag van de gemeente Rotterdam.
   - **Binnen 50 meter van een bestaande kamerverhuurvergunning** — idem.
   - **Opkoopbescherming (wijk-deel)** — vergelijkt de buurt met de 16 wijken waar
     opkoopbescherming geldt (bron: rotterdam.nl/opkoopbescherming).
4. Kan **niet** automatisch checken (en vraagt dit in het rapport aan jou):
   - **WOZ-waarde** — alleen relevant voor huizen in een beschermde wijk. WOZ-waardeloket.nl
     blokkeert geautomatiseerde bevragingen, dus dit vraagt het rapport je met één klik
     handmatig te checken.
   - **Zelfbewoningsplicht in de advertentietekst** — funda blokkeert geautomatiseerd
     bezoek aan advertentiepagina's (Akamai bot-detectie + verplichte CAPTCHA), dus dit
     vraagt het rapport je de advertentietekst zelf even (10 sec) door te lezen.
5. Mailt een dagoverzicht naar `jmmreckman@gmail.com` met alle nog openstaande
   kansen, hoe lang ze al bekend zijn, en welke handmatige checks nog nodig zijn.

**Waarom niet alles automatisch?** Funda en WOZ-waardeloket draaien beide achter
actieve bot-detectie (Akamai + Google reCAPTCHA, resp. een API die stilzwijgend lege
resultaten teruggeeft aan niet-browserverkeer) en verbieden geautomatiseerd bezoek in
hun voorwaarden. Dit programma omzeilt dat bewust niet — dat zou dagelijks CAPTCHA's
moeten kraken en je account/IP kunnen laten blokkeren. In plaats daarvan gebruikt het
alleen legitieme, publieke bronnen (PDOK, de open GIS-kaartlagen van de gemeente
Rotterdam, je eigen Funda-alertmail) en houdt het de paar keer dat je zelf iets moet
natrekken tot een minimum.

## Eenmalige installatie

### 1. Apart Gmail-adres aanmaken

Maak één nieuw Gmail-adres aan, puur voor dit programma, bijvoorbeeld
`rotterdam.kamerverhuur.scanner@gmail.com`. Dit adres:

- ontvangt de dagelijkse Funda-alertmail (stap 2),
- wordt door het programma via IMAP uitgelezen,
- verstuurt het dagrapport naar `jmmreckman@gmail.com`.

Zo blijft je persoonlijke Gmail volledig buiten schot.

### 2. Funda-zoekopdracht + dagelijkse alert instellen

Op funda.nl (ingelogd met een funda-account, dat mag gekoppeld zijn aan het nieuwe
Gmail-adres of gewoon je eigen account met dat e-mailadres als notificatie-adres):

1. Zoek: Koop, Rotterdam (gemeente), type Huis.
2. Klik "Bewaar zoekopdracht".
3. Zet de e-mailfrequentie op **dagelijks** en het notificatie-e-mailadres op het
   nieuwe Gmail-adres uit stap 1.

### 3. Gmail-appwachtwoord aanmaken

Op het nieuwe Gmail-account: zorg dat 2-stapsverificatie aanstaat, ga naar
Google-account > Beveiliging > App-wachtwoorden, en maak een appwachtwoord aan
(bijv. voor "Mail"). Zorg ook dat IMAP aanstaat in Gmail-instellingen
(Instellingen > Doorsturen en POP/IMAP > IMAP inschakelen).

### 4. Project installeren op de zolder-pc

```powershell
git clone <deze-repo-url> kamerverhuur-scanner
cd kamerverhuur-scanner
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env
notepad .env
```

Vul in `.env` in:
- `SCANNER_GMAIL_ADDRESS` — het nieuwe Gmail-adres.
- `SCANNER_GMAIL_APP_PASSWORD` — het appwachtwoord uit stap 3.
- `REPORT_TO_ADDRESS` — `jmmreckman@gmail.com` (staat al goed als default).

### 5. Eerst handmatig testen

```powershell
venv\Scripts\python main.py
```

Check of je een mail ontvangt op `jmmreckman@gmail.com`. De eerste keer zal de
lijst waarschijnlijk leeg zijn totdat funda's eigen alertmail is binnengekomen
(die verstuurt funda 's nachts). Bekijk ook `data\scanner.log` als er iets misgaat.

Twijfel je of de e-mailherkenning goed werkt zodra de eerste echte Funda-alert is
binnengekomen? Download die mail als `.eml` (Gmail: rechtsboven op de mail, drie
puntjes > "Bericht downloaden") en test 'm los:

```powershell
venv\Scripts\python tools\test_email_parsing.py pad\naar\alert.eml
```

### 6. Dagelijkse planning instellen (Windows Taakplanner)

```powershell
.\scripts\registreer_taakplanner.ps1
```

Dit zet een taak "KamerverhuurScannerRotterdam" klaar die dagelijks om 09:00 draait
(en ook draait zodra de pc weer aan staat als hij op dat moment uit was). Testen:

```powershell
Start-ScheduledTask -TaskName "KamerverhuurScannerRotterdam"
```

Verwijderen/opnieuw instellen kan met `scripts\verwijder_taakplanner.ps1`.

## Het dagrapport lezen

Elke rij in "Openstaande kansen" toont:

- **Adres + link** naar de funda-advertentie.
- **Wijk**.
- **Dagen bekend** — dagen sinds dit systeem het huis voor het eerst zag via je
  Funda-alertmail. In de praktijk vrijwel altijd gelijk aan de echte
  "in verkoop sinds"-datum (funda's alert gaat elke nacht uit), maar geen
  harde garantie.
- **Badges** met wat je zelf nog moet checken:
  - `check WOZ-waarde` — alleen als het huis in een opkoopbeschermde wijk ligt.
    Boven de grens (standaard €470.000, aanpasbaar via `OPKOOPBESCHERMING_WOZ_GRENS`
    in `.env`) valt het huis **niet** af.
  - `check zelfbewoningsplicht` — staat altijd, want dit kan niet automatisch.
    Open de link en zoek (Ctrl+F) op "zelfbewoning".

Huizen die automatisch afvielen op het nul-quotumgebied of de 50-meter-check
verdwijnen niet stil: ze staan (voor de dag waarop ze gevonden zijn) in de sectie
"Vandaag afgevallen op geo-checks", met reden — zo kun je fouten in de checks zelf
opmerken.

Een huis verdwijnt automatisch uit "Openstaande kansen" als het 60 dagen
(`LISTING_EXPIRY_DAYS`) niet meer in een nieuwe alertmail is opgedoken — na twee
maanden is een woning ofwel verkocht, ofwel niet meer actueel genoeg.

## Databronnen (en waarom ze robuust genoeg zijn om op te bouwen)

- **Adressen/coördinaten/wijk**: PDOK Locatieserver (`api.pdok.nl`) — landelijke,
  publieke, voor geautomatiseerd gebruik bedoelde overheids-API.
- **Nul-quotumgebieden & kamerverhuurvergunningen (50m)**: de publieke ArcGIS
  Online-kaartlagen achter de officiële Rotterdam-kaart
  (https://experience.arcgis.com/experience/90c482180dbd4ab7ac0040c746ed80f5).
  De gemeente publiceert deze datasets periodiek opnieuw onder een nieuwe naam
  (bijv. `Nulquotum_gebieden_20250902` → een latere datum); het programma zoekt
  daarom bij elke run de actuele laag-URL's dynamisch op via de webmap zelf, in
  plaats van een vaste URL te hardcoden.
- **Opkoopbescherming (wijkenlijst + WOZ-grens)**: handmatig overgenomen van
  rotterdam.nl/opkoopbescherming. Dit is beleid, geen live dataset — check die
  pagina af en toe en pas `rotterdam_scanner/opkoop.py` / `.env` aan als de
  gemeente dit wijzigt.
- **WOZ-waarde per adres**: geen automatische bron beschikbaar (zie hierboven) —
  bewust een handmatige stap.
- **Funda-listings**: je eigen Funda-alertmail, geen scraping.

## Bekende beperkingen

- Adresherkenning uit de funda-alertmail is gebaseerd op het huidige
  funda-URL-patroon. Als funda haar e-maillay-out drastisch verandert, kan de
  parser huizen missen — dit crasht niet, maar zulke huizen belanden dan in
  "Kon niet automatisch verwerkt worden" met de kale link, zodat je ze zelf nog
  ziet.
- Geocoding via PDOK werkt op basis van straatnaam + huisnummer; bij zeer
  ongebruikelijke schrijfwijzen kan dit misgaan. Ook dan: geen crash, wel een
  duidelijke melding in het rapport.
- De "dagen bekend"-teller is gebaseerd op wanneer dit systeem het huis zag, niet
  op een officiële funda-datum.

## Ontwikkelen / tests

```powershell
venv\Scripts\pip install pytest
venv\Scripts\python -m pytest
```
