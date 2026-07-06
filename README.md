# kamerverhuur-scanner

Website voor het beheer van Mahoniestraat 15 (6 kamers, gedeeld met Justin):
controleert of de huur via bunq is binnengekomen, houdt een betaalgeschiedenis
per kamer bij, en helpt bij het genereren van huurcontracten en advertentieteksten.

Login-beveiligd (alleen jij en Justin), bedoeld om op betaalde hosting te draaien
zodat jullie er allebei bij kunnen zonder dat er iets lokaal hoeft te draaien.

## Features

- **Dashboard** - overzicht van de laatste betaalcontrole: hoeveel kamers in orde zijn en welke niet.
- **Kamers** - overzicht van alle 6 kamers, klik door naar een kamer voor huurder, huurprijs,
  contract(en), betaalgeschiedenis en een betrouwbaarheidsscore (% van de controles op tijd/correct betaald).
- **Huurders** - toont en bewerkt de kamer-/huurdersgegevens (Google Sheet blijft de opslag op de
  achtergrond, maar bewerken kan gewoon op de site - geen aparte Google-toegang nodig voor Justin).
- **Betalingen** - knop "Nu controleren": haalt inkomende betalingen van bunq op, koppelt ze aan de
  huurders, toont het resultaat, en schrijft de sheet + geschiedenis bij. Er wordt niets automatisch
  op de achtergrond gecontroleerd en er wordt geen e-mail verstuurd - alles gebeurt on-demand via de site.
- **Contracten** - vult een sjabloon in met de huurdersgegevens tot een concept-huurcontract
  (HTML, printbaar naar PDF vanuit de browser). **Let op:** dit is een voorbeeldsjabloon, geen
  juridisch gecontroleerd contract - zie de waarschuwing verderop.
- **Documenten** - bekijk/upload/download bestanden (puntentellingen, huurcontracten, etc.) uit
  een gedeelde Google Drive-map, rechtstreeks vanaf de site - ook hier is geen aparte Drive-toegang
  voor Justin nodig, de site regelt dat via de service account.
- **Advertentie plaatsen** - genereert een kant-en-klare titel/beschrijving per kamer om te
  plakken op Kamernet. Er is geen publieke Kamernet-API voor individuele verhuurders (alleen een
  zakelijke XML-feed voor makelaars/vastgoedbeheerders via een sales-contact) - vandaar geen
  automatische plaatsing.

## Verwachte kolomindeling in de Google Sheet

Aangesloten op de bestaande huuradministratie-sheet. Tabblad `Mahoniestraat` (of de naam die je
in `GOOGLE_SHEET_WORKSHEET` zet), rij 1 = koppen, data vanaf rij 2, één rij per kamer:

| A Kamer | B Huurder | C Kale huurprijs | D Servicekosten | E Totale huur | F Contract einddatum | G Opmerking | H IBAN | I Zoekwoord | J Status | K Ontvangen bedrag | L Laatst gecontroleerd |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BG straatkant | Henri Maarten Slendebroek | 700,94 | 44,06 | 745,00 | 31-07-2026 | gaat er per 31-07-2026 uit | | | | | |

- Kolom **A t/m G** zijn je bestaande kolommen, die pas je zelf aan (of via de site, zie hieronder).
- Kolom **H en I** (IBAN, Zoekwoord) zijn nieuw - voeg deze koppen toe. Beide zijn optioneel: zonder
  IBAN/Zoekwoord matcht de site op de naam van de huurder.
- Kolom **J, K, L** (Status, Ontvangen bedrag, Laatst gecontroleerd) zijn ook nieuw - voeg de koppen
  toe, de site vult de inhoud zelf.
- **Totale huur** (kolom E) is het bedrag dat de site verwacht via bunq binnen te zien komen (kale
  huur + servicekosten).
- Een lege **Huurder** met een ingevulde **Kamer** betekent: kamer staat leeg.
- Een **somrij** onderaan (Kamer-kolom = "Totalen" of "Totaal") wordt door de site automatisch
  genegeerd - die mag gewoon blijven staan, het dashboard toont ook een eigen totaaloverzicht.

Er wordt automatisch een tweede tabblad **Historie** aangemaakt (naam instelbaar via
`GOOGLE_SHEET_HISTORY_WORKSHEET`) waar elke "Nu controleren"-run een rij per kamer aan toevoegt.
Dat voedt de betaalgeschiedenis en betrouwbaarheidsscore op de kamerpagina's.

## Vereisten

- Python 3.10+ (lokaal testen) of Docker (voor hosting).
- Een Google-account met een Google Sheet.
- Een bunq-rekening (of rekeningen) en de bunq-app (voor de API key).
- Betaalde hosting (aanbevolen, zie verderop) - geen Gmail/e-mail meer nodig.

## Stap 1: Google Sheet voorbereiden

Gebruik je bestaande huuradministratie-sheet. Hernoem het tabblad naar `Mahoniestraat` (of zet de
juiste naam in `GOOGLE_SHEET_WORKSHEET`), en voeg de vijf nieuwe kolomkoppen toe (H t/m L) zoals
hierboven beschreven: IBAN, Zoekwoord, Status, Ontvangen bedrag, Laatst gecontroleerd. Onthoud het
**sheet ID** uit de URL:

```
https://docs.google.com/spreadsheets/d/DIT_IS_HET_SHEET_ID/edit
```

## Stap 2: Google service account aanmaken (voor API-toegang)

1. Ga naar [Google Cloud Console](https://console.cloud.google.com/) en maak een (nieuw) project.
2. **APIs & Services > Library**, zoek **Google Sheets API**, klik **Enable**.
3. **APIs & Services > Credentials > Create Credentials > Service account**. Naam bijv.
   "kamerverhuur-scanner". Rollen zijn niet nodig.
4. Open het service account, tabblad **Keys > Add Key > Create new key**, kies **JSON**. Er wordt
   een JSON-bestand gedownload.
5. Hernoem dit naar `google-service-account.json`, zet het in de projectmap. **Nooit committen**
   (staat in `.gitignore`).
6. Kopieer het `client_email` adres uit het JSON-bestand.
7. Deel de Google Sheet (knop **Delen**) met dat e-mailadres als **Bewerker**.
8. **APIs & Services > Library**, zoek **Google Drive API**, klik **Enable** (voor de Documenten-pagina).
9. Deel jullie bestaande Drive-map met documenten (huurcontracten, puntentelling) ook met hetzelfde
   `client_email` adres, als **Bewerker** (anders kan er niet geupload worden).
10. Zet het map-ID in `.env` als `GOOGLE_DRIVE_FOLDER_ID` - dat is het stuk uit de URL van de map:
    `https://drive.google.com/drive/folders/DIT_IS_HET_MAP_ID`.

## Stap 3: bunq API key aanmaken

1. bunq-app > API key aanmaken (Profiel > Instellingen > Developers/API keys).
2. IP-restrictie: kies **"Alle IP-adressen toestaan"**, tenzij je hosting een vast IP-adres heeft
   (bij de meeste VPS/PaaS-providers is dat wel het geval - controleer dit bij je provider).
3. Wijs de key binnen 4 uur toe en kopieer de waarde.
4. Zet die waarde tijdelijk in `.env` als `BUNQ_API_KEY` en draai eenmalig:

   ```bash
   python scripts/setup_bunq.py
   ```

   Dit registreert dit apparaat bij bunq en slaat de sessie op in het bestand uit `BUNQ_CONF_FILE`
   (`bunq_production.conf`). Dit bestand moet naar je hostingomgeving mee (zie Stap 6) - **nooit
   committen**.
5. Zet in `.env` ook `BUNQ_REKENING_IBAN` op het IBAN van de **specifieke rekening** waar de
   Mahoniestraat-huur op binnenkomt (te vinden in de bunq-app bij die rekening). Dit is belangrijk:
   zonder dit scant de site *al* je bunq-rekeningen (inclusief privé en je andere panden), wat
   zowel privacygevoelig is als de betaalcontrole kan laten missen door de paginalimiet.

> bunq heeft de officiële Python SDK (`bunq_sdk`, gebruikt in dit project) gemarkeerd als niet
> langer actief onderhouden. Hij werkt op dit moment nog goed; zie https://doc.bunq.com als bunq
> ooit iets incompatibels wijzigt.

## Stap 4: gebruikers aanmaken (login voor jou en Justin)

```bash
python scripts/create_user.py jouw_gebruikersnaam
python scripts/create_user.py justin
```

Dit vraagt een wachtwoord (niet zichtbaar tijdens typen) en slaat het gehasht op in `users.json`
(**nooit committen**). Zet ook een willekeurige lange random string in `.env` als
`FLASK_SECRET_KEY` (bijv. met `python -c "import secrets; print(secrets.token_hex(32))"`).

## Stap 5: lokaal testen

```bash
git clone <deze-repo>
cd kamerverhuur-scanner
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# vul .env in (sheet ID, bunq, FLASK_SECRET_KEY, etc.)

python scripts/setup_bunq.py
python scripts/create_user.py jouw_gebruikersnaam

python -m webapp.app
```

Ga naar `http://127.0.0.1:5000`, log in, en test de knoppen (begin met "Betalingen > Nu
controleren"). Los eventuele fouten op (meestal een verkeerde sheet-naam, IBAN, of ontbrekende
sheet-toegang) voordat je gaat hosten.

## Stap 6: hosting (aanbevolen: Render, betaald, geen zolder-pc nodig)

Zelf een pc thuis altijd laten aanstaan is gratis, maar betekent poorten openzetten in je router,
een oplossing voor je (waarschijnlijk wisselende) thuis-IP, en dat de site plat gaat als je pc of
internet even wegvalt. Voor een paar euro per maand is een VPS/PaaS stabieler en simpeler te
beheren. Render.com is een prettige optie omdat het rechtstreeks vanaf GitHub deployt via de
meegeleverde `Dockerfile`, zonder dat je zelf een server hoeft te beheren.

1. Maak een account op [render.com](https://render.com), koppel je GitHub-repo.
2. **New > Web Service**, kies deze repo. Render herkent de `Dockerfile` automatisch.
3. Voeg een **Persistent Disk** toe (bijv. 1 GB, mount path `/app/data`) - hierop bewaar je de
   bestanden die niet in git staan: `google-service-account.json`, `bunq_production.conf`,
   `users.json`, `laatste_resultaat.json`, en de map `gegenereerde_contracten/`.
4. Zet de environment variables (Render dashboard > Environment) zoals in `.env.example`, maar
   met paden die naar de disk wijzen, bijvoorbeeld:
   ```
   GOOGLE_SERVICE_ACCOUNT_FILE=/app/data/google-service-account.json
   BUNQ_CONF_FILE=/app/data/bunq_production.conf
   USERS_FILE=/app/data/users.json
   ```
5. Na de eerste deploy: open een shell op de service (Render dashboard > Shell) en upload/plak de
   inhoud van je `google-service-account.json` naar `/app/data/google-service-account.json`, en
   draai daar `python scripts/setup_bunq.py` en `python scripts/create_user.py <naam>` (met de
   env-variabelen die al door Render zijn ingesteld).
6. Render geeft je een `https://...onrender.com` URL - deel die met Justin, samen met zijn
   gebruikersnaam/wachtwoord.

Andere prima alternatieven: Railway.app (vergelijkbaar met Render) of een goedkope VPS bij
Hetzner (~€4/maand) met de `Dockerfile` en een reverse proxy (bijv. Caddy) voor gratis HTTPS -
dat laatste vraagt wel wat meer zelf-beheer (patches, herstarten na een reboot).

### Lokaal met Docker testen

```bash
docker build -t kamerverhuur-scanner .
docker run --rm -p 8000:8000 \
  -v "$(pwd)/.env:/app/.env" \
  -v "$(pwd)/google-service-account.json:/app/google-service-account.json" \
  -v "$(pwd)/bunq_production.conf:/app/bunq_production.conf" \
  -v "$(pwd)/users.json:/app/users.json" \
  kamerverhuur-scanner
```

## Belangrijke kanttekeningen

- **Huurcontracten zijn een voorbeeldsjabloon.** `contract_templates/huurovereenkomst_voorbeeld.html`
  bevat placeholder-bepalingen, geen juridisch gecontroleerde tekst. Vervang de inhoud door een
  gecontroleerd modelcontract (bijv. de modelhuurovereenkomst van de Rijksoverheid of Woonbond)
  voordat je een gegenereerd contract laat ondertekenen. De site zelf toont deze waarschuwing ook
  bij het genereren.
- **Geen automatische Kamernet-plaatsing.** De advertentieknop genereert alleen tekst om te
  kopiëren/plakken.
- **Matching op naam is een benadering.** Bij twijfel is een IBAN of vast zoekwoord per kamer
  betrouwbaarder dan matchen op naam.
- **Betrouwbaarheidsscore** is simpel gehouden: het percentage uitgevoerde controles waarbij de
  status "Betaald" was. Geen tracking van hoeveel dagen te laat, alleen of het bedrag klopte op
  het moment van controleren.
- **Downloaden van Google Docs/Sheets uit de Documenten-map** levert automatisch een PDF-export op
  (die bestandstypen kun je niet als los binair bestand downloaden) - voor al geuploade PDF's/foto's
  werkt downloaden zoals verwacht.

## Beveiliging

- `.env`, `google-service-account.json`, `bunq_production.conf` en `users.json` bevatten geheimen
  en staan in `.gitignore` - commit ze nooit, ook niet naar een privé-fork.
- Gebruik de Google service account en bunq API key alleen voor dit doel.
- Deel de site-login alleen met jou en Justin.

## Problemen oplossen

- **`pip install` faalt op `bunq_sdk` met een `install_layout` fout** - verouderde `setuptools`;
  draai `pip install --upgrade pip setuptools wheel` en probeer opnieuw.
- **"Kon bunq-context bestand niet vinden"** - draai `python scripts/setup_bunq.py` (opnieuw, na
  het instellen van `BUNQ_CONF_FILE`).
- **Kamer staat op "Nog niet ontvangen" terwijl er wel betaald is** - controleer IBAN/naam/Zoekwoord
  in de sheet.
- **Inloggen lukt niet** - controleer of `USERS_FILE` naar het juiste pad wijst en of
  `scripts/create_user.py` succesvol is gedraaid.
