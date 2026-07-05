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
   - **Opkoopbescherming (wijk + WOZ-waarde)** — vergelijkt de buurt met de 16 wijken
     waar opkoopbescherming geldt (bron: rotterdam.nl/opkoopbescherming) én haalt voor
     die huizen automatisch de WOZ-waarde op via een betaalde WOZ-API (zie stap 3
     hieronder). Dit is dus volledig automatisch, geen dagelijkse handmatige lijst.
4. Haalt de **officiële oppervlakte** van het BAG (Basisregistratie Adressen en
   Gebouwen) op — publieke landelijke data, vaak nauwkeuriger dan de advertentietekst.
5. Sorteert de openstaande kansen op **vraagprijs per m²** (op basis van die
   BAG-oppervlakte), niet op datum — hoe lang een huis al bekend is staat er sowieso
   al apart bij.
6. Haalt woningen die **niet meer gewoon te koop staan** (onder bod, verkocht, in
   onderhandeling) automatisch uit de lijst — zie de kanttekening hieronder, dit
   vereist wel één kleine, eenmalige handeling per huis van jouw kant.
7. Kan **niet** automatisch checken (en vraagt dit in het rapport aan jou):
   - **Zelfbewoningsplicht in de advertentietekst** — funda blokkeert geautomatiseerd
     bezoek aan advertentiepagina's (Akamai bot-detectie + verplichte CAPTCHA), dus dit
     vraagt het rapport je de advertentietekst zelf even (10 sec) door te lezen. Dit
     staat bij elk overgebleven huis, maar dat zijn er dankzij de eerdere checks nog
     maar een handjevol per dag.
8. Mailt een dagoverzicht naar `jmmreckman@gmail.com` met alle nog openstaande
   kansen, hoe lang ze al bekend zijn, en welke (weinige) handmatige check nog nodig is.

**Over "niet meer te koop" (onder bod/verkocht):** funda's dagelijkse zoekopdracht-
alert meldt alleen NIEUWE woningen, nooit dat een eerder geziene woning van status is
veranderd — dat is inherent aan hoe die functie werkt, ongeacht wie hem bouwt. Funda
heeft daarnaast wél een aparte, officiële functie die dit oplost: de
["favorieten-e-mail"](https://www.funda.nl/meer-weten/producten-en-diensten/nieuw/nieuwe-favorieten-e-mail/) —
maximaal één e-mail per dag met alle wijzigingen (status, prijs) van woningen die je
zelf als favoriet hebt gemarkeerd. Dit programma leest ook die e-mail mee en haalt een
huis automatisch uit "Openstaande kansen" zodra hij "onder bod", "verkocht" of "in
onderhandeling" meldt. De enige eis: **markeer nieuwe kandidaten in het rapport zelf
even als favoriet op funda.nl** (één klik) — daarna is het weer volledig automatisch
voor dat huis. Doe je dat niet, dan blijft het huis gewoon (tot max. 60 dagen) in de
lijst staan totdat het vanzelf verloopt. Zie ook "Bekende beperkingen" hieronder: de
tekstherkenning hiervoor is best-effort, net als bij de prijsherkenning.

**Waarom niet alles automatisch?** Funda draait achter actieve bot-detectie (Akamai +
verplichte Google reCAPTCHA) en verbiedt geautomatiseerd bezoek in de voorwaarden. Dit
programma omzeilt dat bewust niet — dat zou dagelijks CAPTCHA's moeten kraken en je
account/IP kunnen laten blokkeren. Voor de WOZ-waarde bestaat wél een legitiem
alternatief: wozwaardeloket.nl zelf blokkeert geautomatiseerde bevragingen, maar er
zijn commerciële partijen (zoals woz-api.nl) die WOZ-data via een normale, betaalde
API aanbieden — geen scraping, gewoon een leverancier inhuren. Dat gebruikt dit
programma voor de opkoopbescherming-check. Alleen de zelfbewoningsplicht-tekstcheck
blijft (noodgedwongen) een korte handmatige stap.

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

**Belangrijk:** plak dit wachtwoord nergens in een chatgesprek of e-mail — vul het
alleen rechtstreeks in `.env` in op de zolder-pc zelf (stap 4). Dat bestand verlaat
die machine nooit en staat in `.gitignore`.

### 3b. WOZ-API-key aanmaken (voor de automatische opkoopbescherming-check)

Registreer een gratis account op [woz-api.nl](https://woz-api.nl/Identity/Account/Register)
en maak een API-key aan. Kosten zijn ordegrootte €0,58–0,71 per uniek adres dat je
opvraagt (zie [woz-api.nl/woz-api-prijs](https://woz-api.nl/woz-api-prijs)) — omdat
alleen huizen in een opkoopbeschermde wijk gecheckt worden, en elk adres maar één
keer (het resultaat wordt lokaal onthouden), blijft dit in de praktijk een paar euro
per maand. Zonder deze key blijft het programma gewoon werken, maar valt het voor
die huizen terug op een handmatige "check WOZ-waarde"-melding in het rapport.

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
- `WOZ_API_KEY` — de key uit stap 3b (laat leeg om de handmatige WOZ-fallback te gebruiken).

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

"Openstaande kansen" is gesorteerd op **vraagprijs per m² (laagste eerst)**, op basis
van de officiële BAG-oppervlakte. Elke rij toont:

- **Adres + link** naar de funda-advertentie.
- **Wijk**.
- **Vraagprijs**, **Oppervlakte** (`... m² (BAG)`, dus de officiële maat, niet de
  advertentietekst) en **€/m²** — als de prijs een keer niet herkend kon worden uit
  de alertmail, staat het huis onderaan (zie "Bekende beperkingen").
- **Dagen bekend** — dagen sinds dit systeem het huis voor het eerst zag via je
  Funda-alertmail. In de praktijk vrijwel altijd gelijk aan de echte
  "in verkoop sinds"-datum (funda's alert gaat elke nacht uit), maar geen
  harde garantie.
- **Badges** met wat je zelf nog moet checken:
  - `check WOZ-waarde` — verschijnt normaal NIET meer: met een `WOZ_API_KEY` wordt dit
    automatisch gecheckt (boven de grens, standaard €470.000 en aanpasbaar via
    `OPKOOPBESCHERMING_WOZ_GRENS`, valt het huis niet af, en zie je die badge dus
    niet). De badge duikt alleen op als de WOZ-opvraging een keer mislukte — kijk dan
    naar de opmerking eronder voor de reden.
  - `markeer favoriet op funda` — alleen bij huizen die vandaag voor het eerst in de
    lijst staan. Eén klik op funda.nl, en daarna detecteert het systeem automatisch
    als het huis onder bod of verkocht gaat (zie hierboven).
  - `check zelfbewoningsplicht` — staat altijd, want dit kan niet automatisch.
    Open de link en zoek (Ctrl+F) op "zelfbewoning".

Huizen die automatisch afvielen op het nul-quotumgebied of de 50-meter-check
verdwijnen niet stil: ze staan (voor de dag waarop ze gevonden zijn) in de sectie
"Vandaag afgevallen op geo-checks", met reden — zo kun je fouten in de checks zelf
opmerken. Huizen die via de favorieten-e-mail als onder bod/verkocht/in onderhandeling
gedetecteerd zijn, staan apart in "Niet meer te koop".

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
- **WOZ-waarde per adres**: [woz-api.nl](https://woz-api.nl/) — een commerciële,
  betaalde API met normale API-key-authenticatie (geen scraping). Bevraagd op
  BAG-nummeraanduiding-ID (uit de PDOK-geocode), niet op vrije tekst, dus
  ondubbelzinnig. Elk adres wordt maar één keer bevraagd (het resultaat blijft in
  `data/state.json` staan); zonder `WOZ_API_KEY` valt dit terug op een handmatige
  melding in het rapport.
- **Officiële oppervlakte**: de publieke PDOK BAG-WFS (`service.pdok.nl/lv/bag`) —
  landelijke basisregistratie, geen API-key nodig, bevraagd op het BAG-verblijfsobject-ID
  (uit de PDOK-geocode). Dit is de "echte" maat, die geregeld afwijkt van wat in een
  advertentie staat.
- **Vraagprijs en status (onder bod/verkocht)**: uit de opmaak van je eigen
  Funda-mails (de nieuwe-woningen-alert resp. de favorieten-e-mail), geen scraping.
- **Funda-listings**: je eigen Funda-alertmail, geen scraping.

## Bekende beperkingen

- Adresherkenning uit de funda-alertmail is gebaseerd op het huidige
  funda-URL-patroon. Als funda haar e-maillay-out drastisch verandert, kan de
  parser huizen missen — dit crasht niet, maar zulke huizen belanden dan in
  "Kon niet automatisch verwerkt worden" met de kale link, zodat je ze zelf nog
  ziet.
- **Prijs- en statusherkenning zijn kwetsbaarder dan de rest.** Adres/object-ID komen
  rechtstreeks uit de funda-URL (stabiel), maar prijs en status ("onder bod" e.d.)
  worden gezocht in de tekst rond elke link in de e-mail — dat is afhankelijk van
  funda's actuele e-mail-opmaak. Werkt dit een keer niet goed, gebruik dan
  `tools/test_email_parsing.py` tegen een opgeslagen `.eml` om te zien wat er wel/niet
  herkend wordt, en stel zo nodig de patronen in `rotterdam_scanner/funda_mail.py` bij.
- De "niet meer te koop"-detectie werkt alleen voor huizen die je zelf als favoriet
  hebt gemarkeerd op funda.nl — zonder die klik blijft een verkocht huis gewoon
  (tijdelijk) in de lijst staan.
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
