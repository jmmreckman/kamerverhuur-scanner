# kamerverhuur-scanner

Eén website voor het beheer van al je verhuurpanden: controleert of de huur via
bunq is binnengekomen, houdt een betaalgeschiedenis per kamer bij, waarschuwt
wanneer een tijdelijk huurcontract binnenkort moet worden aangezegd, en helpt
bij het genereren van huurcontracten en advertentieteksten.

Alle panden zitten op één domein. Na inloggen kies je (via een dropdown
rechtsboven, als je toegang hebt tot meer dan één pand) welk pand je bekijkt.
Toegang is per gebruiker in te stellen: jij kan bijvoorbeeld overal bij, terwijl
Justin alleen bij de Mahoniestraat kan. Een nieuw pand toevoegen betekent een
blok toevoegen aan `properties.json` - geen nieuwe website, container of domein
nodig.

## Features

- **Pandkiezer** - na inloggen zie je (of word je automatisch doorgestuurd naar,
  als je er maar één hebt) een overzicht van de panden waar je toegang toe hebt.
- **Toegangscontrole per pand** - probeer je bij een pand te komen waar je geen
  toegang toe hebt, dan krijg je een duidelijke melding ("geen toegang, vraag de
  beheerder") in plaats van een foutmelding.
- **Gebruikersbeheer** - gebruikers met toegang tot alle panden zien een
  "Gebruikers"-knop in de site zelf, waar nieuwe collega's/mede-eigenaren
  toegevoegd kunnen worden en per gebruiker aan te vinken is bij welke panden
  diegene mag (of "alle panden"). Geen command line meer voor nodig na de
  eerste installatie.
- **Dashboard** - overzicht van de laatste betaalcontrole per pand, plus een
  waarschuwing als een tijdelijk huurcontract binnenkort (of al) aangezegd moet
  worden (wettelijk verplicht 1-3 maanden voor de einddatum, art. 7:271 BW).
- **Kamers** - overzicht van alle kamers van het gekozen pand, klik door naar een
  kamer voor huurder, huurprijs, contract(en), betaalgeschiedenis en een
  betrouwbaarheidsscore (% van de controles op tijd/correct betaald).
- **Huurders** - toont en bewerkt de kamer-/huurdersgegevens (Google Sheet blijft
  de opslag op de achtergrond, maar bewerken kan gewoon op de site - geen aparte
  Google-toegang nodig voor medegebruikers).
- **Betalingen** - knop "Nu controleren": haalt inkomende betalingen van bunq op
  (alleen van de bunq-rekening die bij dat pand hoort), koppelt ze aan de
  huurders, toont het resultaat, en schrijft de sheet + geschiedenis bij. Er
  wordt niets automatisch op de achtergrond gecontroleerd - alles gebeurt
  on-demand via de site.
- **Contracten** - vult een sjabloon in met de huurdersgegevens tot een concept-
  huurcontract (HTML, printbaar naar PDF vanuit de browser). **Let op:** dit is
  een voorbeeldsjabloon, geen juridisch gecontroleerd contract - zie de
  waarschuwing verderop.
- **Documenten** - echte mappenstructuur van de Google Drive-map van het
  gekozen pand: mappen openen, bestanden slepen om te uploaden, nieuwe mappen
  aanmaken en downloaden, rechtstreeks vanaf de site.
- **Advertentie plaatsen** - genereert een kant-en-klare titel/beschrijving per
  kamer (met het adres van het juiste pand) om te plakken op Kamernet. Er is
  geen publieke Kamernet-API voor individuele verhuurders (alleen een zakelijke
  XML-feed voor makelaars/vastgoedbeheerders via een sales-contact) - vandaar
  geen automatische plaatsing.
- **Publieke aanbodpagina** (`/aanbod`, Engelstalig, geen login nodig) - toont
  alle kamers die je als "te huur" hebt aangevinkt, met foto's/video's en een
  "Apply"-knop die naar een aanmeldformulier leidt. Zie "Aanbod & aanmeldingen"
  hieronder.
- **Aanmeldingen** - reacties op de aanbodpagina komen (met een upload van hun
  bewijs van inschrijving) in een overzicht terecht dat alleen beheerders van
  dat specifieke pand kunnen zien - met één druk op de knop weer leeg te maken
  zodra je een huurder hebt gekozen.

## Aanbod & aanmeldingen (publieke kamerlisting)

Naast het besloten beheergedeelte heeft de site ook een openbare, Engelstalige
aanbodpagina - handig omdat de meeste kamerzoekers internationale studenten
zijn.

- **Een kamer te huur zetten**: ga naar de kamerpagina (Kamers > kies een
  kamer) en klik op **"Aanbod beheren"**. Daar vink je "Deze kamer is te huur"
  aan, schrijf je een Engelse omschrijving (of gebruik de voorgestelde tekst),
  en upload je foto's/video's (drag-and-drop, net als bij Documenten). Zodra
  je opslaat, verschijnt de kamer op `steenhub.nl/aanbod` en op zijn eigen
  deelbare pagina `steenhub.nl/aanbod/<pand-slug>/<kamernaam>` - geen login
  nodig om die te bekijken.
- **Reageren**: bezoekers klikken op "Apply for this room" en vullen een
  formulier in (naam, contactgegevens, studie, studentnummer, gewenste
  ingangsdatum/huurduur, inkomsten, borgsteller ja/nee, voorkeur voor een
  fysieke bezichtiging of videobellen, en een verplichte upload van hun bewijs
  van inschrijving). Bewust een aantal extra vragen, zodat vooral serieus
  geïnteresseerden de moeite nemen te reageren. Het bewijs van inschrijving
  wordt automatisch in de Drive-map van het pand gezet (onder
  "Aanmeldingen/<kamernaam>/") - dat is dus nergens publiek te downloaden.
- **Aanmeldingen bekijken**: ga naar **"Aanmeldingen"** in de site-navigatie
  (alleen zichtbaar/toegankelijk voor ingelogde beheerders van dat pand) voor
  een overzicht van alle reacties, met een link naar het geuploade bewijs van
  inschrijving. Heb je een huurder gekozen? Klik op **"Lijst wissen"** om
  helemaal opnieuw te beginnen voor de volgende keer dat de kamer vrijkomt.
- Nog geen ID-controle, inkomenscontrole of automatische contractopstelling
  vanuit een aanmelding - dat blijft (bewust) een latere stap, die begint pas
  als je een kandidaat definitief hebt gekozen.

## Verwachte kolomindeling in de Google Sheet (per pand)

Elk pand heeft zijn eigen tabblad/sheet, aangesloten op je bestaande
huuradministratie. Rij 1 = koppen, data vanaf rij 2, één rij per kamer:

| A Kamer | B Huurder | C Kale huurprijs | D Servicekosten | E Totale huur | F Contract einddatum | G Opmerking | H IBAN | I Zoekwoord | J Status | K Ontvangen bedrag | L Laatst gecontroleerd | M Beschikbaar | N Advertentie omschrijving | O Advertentie map-ID |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BG straatkant | Henri Maarten Slendebroek | 700,94 | 44,06 | 745,00 | 31-07-2026 | gaat er per 31-07-2026 uit | | | | | | | | |

- Kolom **A t/m G** zijn je bestaande kolommen, die pas je zelf aan (of via de
  site, zie hieronder).
- Kolom **H en I** (IBAN, Zoekwoord) zijn nieuw - voeg deze koppen toe. Beide
  zijn optioneel: zonder IBAN/Zoekwoord matcht de site op de naam van de
  huurder.
- Kolom **J, K, L** (Status, Ontvangen bedrag, Laatst gecontroleerd) zijn ook
  nieuw - voeg de koppen toe, de site vult de inhoud zelf.
- Kolom **M, N, O** (Beschikbaar, Advertentie omschrijving, Advertentie
  map-ID) horen bij de publieke aanbodpagina - voeg de koppen toe, maar vul de
  inhoud niet zelf in: dat doet de site via de "Aanbod beheren"-knop op de
  kamerpagina.
- **Totale huur** (kolom E) is het bedrag dat de site verwacht via bunq binnen
  te zien komen (kale huur + servicekosten).
- Een lege **Huurder** met een ingevulde **Kamer** betekent: kamer staat leeg.
- Een **somrij** onderaan (Kamer-kolom = "Totalen" of "Totaal") wordt door de
  site automatisch genegeerd - die mag gewoon blijven staan.
- **Contract einddatum** (kolom F, formaat `dd-mm-jjjj`) wordt ook gebruikt
  voor de aanzeg-waarschuwing op het dashboard. Leeg laten (of "onbepaalde
  tijd" erin zetten) als het contract geen einddatum heeft.

Er wordt automatisch een tweede tabblad (**Historie**, naam instelbaar per
pand) aangemaakt waar elke "Nu controleren"-run een rij per kamer aan toevoegt.
Dat voedt de betaalgeschiedenis en betrouwbaarheidsscore op de kamerpagina's.

Ook wordt automatisch een derde tabblad (**Aanmeldingen**, naam ook instelbaar
per pand) aangemaakt waar reacties op de publieke aanbodpagina in
terechtkomen - zie "Aanbod & aanmeldingen" hierboven.

## Vereisten

- Python 3.10+ (lokaal testen) of Docker (voor hosting).
- Eén Google-account met voor elk pand een Google Sheet (mag ook allemaal
  tabbladen in dezelfde spreadsheet zijn).
- Eén of meerdere bunq-rekeningen (één specifieke rekening per pand) en de
  bunq-app (voor de API key).
- Een eigen VPS met domein (zie Stap 7) - geen Gmail/e-mail meer nodig.

## Stap 1: Google Sheets voorbereiden

Gebruik je bestaande huuradministratie-sheet(s). Voor elk pand: hernoem het
tabblad naar iets herkenbaars, en voeg de vijf nieuwe kolomkoppen toe (H t/m L)
zoals hierboven beschreven: IBAN, Zoekwoord, Status, Ontvangen bedrag, Laatst
gecontroleerd. Onthoud per pand het **sheet ID** uit de URL:

```
https://docs.google.com/spreadsheets/d/DIT_IS_HET_SHEET_ID/edit
```

## Stap 2: Google service account aanmaken (voor API-toegang, eenmalig, voor alle panden samen)

1. Ga naar [Google Cloud Console](https://console.cloud.google.com/) en maak
   een (nieuw) project.
2. **APIs & Services > Library**, zoek **Google Sheets API**, klik **Enable**.
3. **APIs & Services > Credentials > Create Credentials > Service account**.
   Naam bijv. "kamerverhuur-scanner". Rollen zijn niet nodig.
4. Open het service account, tabblad **Keys > Add Key > Create new key**, kies
   **JSON**. Er wordt een JSON-bestand gedownload.
5. Hernoem dit naar `google-service-account.json`, zet het in de projectmap.
   **Nooit committen** (staat in `.gitignore`).
6. Kopieer het `client_email` adres uit het JSON-bestand.
7. Deel **elke** Google Sheet (knop **Delen**) met dat e-mailadres als
   **Bewerker**.
8. **APIs & Services > Library**, zoek **Google Drive API**, klik **Enable**
   (voor de Documenten-pagina).
9. Deel de Drive-map met documenten van **elk pand** ook met hetzelfde
   `client_email` adres, als **Bewerker** (anders kan er niet geupload
   worden). Onthoud per pand het map-ID uit de URL van de map:
   `https://drive.google.com/drive/folders/DIT_IS_HET_MAP_ID`.

Eén service account volstaat voor alle panden - je deelt hem gewoon met meer
sheets en Drive-mappen.

## Stap 3: bunq API key aanmaken (eenmalig, voor alle rekeningen samen)

1. bunq-app > API key aanmaken (Profiel > Instellingen > Developers/API keys).
2. IP-restrictie: kies **"Alle IP-adressen toestaan"**, tenzij je VPS een vast
   IP-adres heeft (meestal wel het geval - controleer dit bij je provider).
3. Wijs de key binnen 4 uur toe en kopieer de waarde.
4. Zet die waarde tijdelijk in `app.env`/`.env` als `BUNQ_API_KEY` en draai
   eenmalig:

   ```bash
   python scripts/setup_bunq.py
   ```

   Dit registreert dit apparaat bij bunq en slaat de sessie op in het bestand
   uit `BUNQ_CONF_FILE` (`bunq_production.conf`). Dit bestand moet naar je
   VPS mee (zie Stap 7) - **nooit committen**. Daarna mag `BUNQ_API_KEY` weer
   verwijderd worden uit `app.env`/`.env`.

> bunq heeft de officiële Python SDK (`bunq_sdk`, gebruikt in dit project)
> gemarkeerd als niet langer actief onderhouden. Hij werkt op dit moment nog
> goed; zie https://doc.bunq.com als bunq ooit iets incompatibels wijzigt.

## Stap 4: `properties.json` instellen (jouw panden)

Elk pand (Google Sheet, Drive-map, bunq-rekening) staat als één blok in
`properties.json` (dat bestand staat in `.gitignore`, nooit committen). Kopieer
het voorbeeld en vul het in:

```bash
cp properties.json.example properties.json
```

```json
[
  {
    "slug": "mahoniestraat",
    "naam": "Mahoniestraat 15",
    "google_sheet_id": "...het sheet ID uit stap 1...",
    "google_sheet_worksheet": "Mahoniestraat",
    "history_worksheet": "Historie",
    "google_drive_folder_id": "...het map-ID uit stap 2, of null...",
    "bunq_rekening_iban": "NL81BUNQ2163127125"
  }
]
```

- **slug**: verschijnt in de URL (`/pand/mahoniestraat/...`), alleen
  kleine letters/cijfers/streepjes.
- **bunq_rekening_iban**: het IBAN van de **specifieke rekening** waar de huur
  van dít pand op binnenkomt. Belangrijk: zonder correct IBAN scant de site de
  verkeerde rekening, wat zowel privacygevoelig is (als het een andere/prive
  rekening raakt) als de betaalcontrole kan laten missen.
- Voeg een nieuw pand later toe door simpelweg een nieuw blok aan de lijst toe
  te voegen - geen nieuwe container, service of domein nodig, gewoon
  `docker compose restart app` (of de app herstarten bij lokaal draaien).

## Stap 5: de eerste gebruiker aanmaken

De allereerste gebruiker (jijzelf, met toegang tot alle panden) maak je eenmalig
via de command line aan, omdat er dan nog niemand is die kan inloggen op de
gebruikersbeheer-pagina:

```bash
python scripts/create_user.py jouw_gebruikersnaam --alle-panden
```

- `--alle-panden`: deze gebruiker mag bij elk pand in `properties.json`, ook
  panden die je later toevoegt.
- `--panden slug1,slug2`: (alternatief) deze gebruiker mag alleen bij de
  genoemde panden (comma-gescheiden slugs).

Dit vraagt een wachtwoord (niet zichtbaar tijdens typen) en slaat het gehasht
op in `users.json` (**nooit committen**).

**Alle volgende gebruikers** (bijv. Justin) maak je niet meer via de command
line aan, maar gewoon op de site zelf: log in als jouw net aangemaakte
gebruiker, klik rechtsboven op **"Gebruikers"** (die knop is alleen zichtbaar
voor gebruikers met toegang tot alle panden), en voeg daar een nieuwe
gebruiker toe met een wachtwoord en de panden waar diegene bij mag. Wachtwoord
wijzigen of toegang aanpassen kan daar ook, evenals een gebruiker verwijderen.
Je kunt jezelf niet per ongeluk je eigen beheerrechten ontnemen of jezelf
verwijderen - dat voorkomt dat je buitengesloten raakt.

`scripts/create_user.py` blijft ook daarna gewoon werken (bijv. als
noodoplossing als je een keer niet kan inloggen).

Zet daarnaast een willekeurige lange random string in `app.env`/`.env` als
`FLASK_SECRET_KEY` (bijv. met `python -c "import secrets; print(secrets.token_hex(32))"`).

## Stap 6: lokaal testen

```bash
git clone <deze-repo>
cd kamerverhuur-scanner
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
cp properties.json.example properties.json
# vul .env in (paden, bunq, FLASK_SECRET_KEY) en properties.json (je panden)

python scripts/setup_bunq.py
python scripts/create_user.py jouw_gebruikersnaam --alle-panden

python -m webapp.app
```

Ga naar `http://127.0.0.1:5000`, log in, en test de knoppen (begin met
"Betalingen > Nu controleren"). Los eventuele fouten op (meestal een verkeerde
sheet-naam, IBAN, of ontbrekende sheet-toegang) voordat je gaat hosten.

Los van de website kun je een pand ook vanaf de command line controleren,
handig om snel een koppeling te testen:

```bash
python main.py --lijst                 # toon alle pand-slugs uit properties.json
python main.py mahoniestraat --dry-run # controleer, print alleen op het scherm
python main.py mahoniestraat           # controleer en schrijf sheet + geschiedenis bij
```

## Stap 7: hosting op een eigen VPS (Docker Compose + Caddy)

Eén VPS (bv. Hetzner of Strato, een paar euro per maand) host de hele site -
alle panden zitten immers in dezelfde applicatie/container. [Caddy](https://caddyserver.com/)
draait als reverse-proxy ervoor en regelt automatisch gratis HTTPS voor je
domein. Alle configuratie hiervoor staat in de map `deploy/`:

- `deploy/docker-compose.yml` - één `app`-service (de website) + één
  `caddy`-service (reverse proxy/HTTPS).
- `deploy/Caddyfile` - domeinblok voor `steenhub.nl` (met `www.` redirect).
- `deploy/app.env.example` - kopieer naar `deploy/app.env` en vul in.
- `deploy/setup-vps.sh` - eenmalig script dat Docker installeert, automatische
  beveiligingsupdates inschakelt en de firewall instelt.

Kort stappenplan op een verse VPS:

```bash
# op de VPS, als root/sudo:
curl -fsSL https://raw.githubusercontent.com/<jouw-fork>/kamerverhuur-scanner/main/deploy/setup-vps.sh | bash
# of: kopieer het script en draai het lokaal na git clone

git clone <deze-repo> /opt/kamerverhuur-scanner
cd /opt/kamerverhuur-scanner
git checkout claude/student-housing-rent-tracker-u2fb2f

cd deploy
cp app.env.example app.env
mkdir -p data
# zet in data/: google-service-account.json, bunq_production.conf,
#               properties.json, users.json (aanmaken via docker compose run, zie hieronder)
# vul app.env in

# wijs het A-record van je domein naar het IP van deze VPS voordat je Caddy start

docker compose run --rm app python scripts/setup_bunq.py
docker compose run --rm app python scripts/create_user.py jouw_gebruikersnaam --alle-panden

docker compose up -d --build
```

### Automatisch deployen (GitHub Actions)

Nadat de VPS eenmaal draait, hoef je niet steeds handmatig `git pull` +
`docker compose up -d --build` te draaien: `.github/workflows/deploy.yml`
doet dit automatisch bij elke push naar de branch. Eenmalige instelling:

1. Genereer een apart SSH-sleutelpaar specifiek voor deployen (niet je eigen
   sleutel hergebruiken), en zet de publieke helft in `~/.ssh/authorized_keys`
   op de VPS (naast je eigen sleutel, niet in plaats daarvan).
2. Zet in de repo-instellingen (**Settings > Secrets and variables >
   Actions**) drie secrets: `DEPLOY_SSH_KEY` (de privésleutel),
   `DEPLOY_HOST` (het IP-adres van de VPS), `DEPLOY_USER` (meestal `root`).
3. Klaar - vanaf nu deployt elke push naar de branch automatisch. Ook handig:
   **Actions**-tab in GitHub > workflow **"Deploy naar VPS"** > **Run
   workflow** om een deploy handmatig opnieuw te triggeren zonder nieuwe code.

Log daarna in op de site als `jouw_gebruikersnaam` en maak verdere gebruikers
(zoals Justin) aan via de **"Gebruikers"**-knop op de site zelf (zie Stap 5) -
dat hoeft dus niet meer via de command line.

Een nieuw pand toevoegen (later): een blok toevoegen aan `properties.json` op
de VPS, en `docker compose restart app` - geen nieuwe container, service of
domein nodig, het is dezelfde site.

Waarom een VPS in plaats van een beheerde dienst (Render/Railway)? Dat scheelt
flink in kosten (een paar euro per maand totaal, in plaats van betalen per
dienst), en je hebt volledige vrijheid - geen updates van een externe partij
die zonder aankondiging iets breken. Het `setup-vps.sh`-script zorgt dat het
dagelijkse onderhoud minimaal blijft (automatische beveiligingsupdates,
containers herstarten zichzelf bij een crash).

### Lokaal met Docker testen (los van de VPS)

```bash
docker build -t kamerverhuur-scanner .
docker run --rm -p 8000:8000 \
  -v "$(pwd)/deploy/app.env:/app/.env" \
  -v "$(pwd)/data:/app/data" \
  kamerverhuur-scanner
```

(`data/` bevat dan `google-service-account.json`, `bunq_production.conf`,
`properties.json` en `users.json`, zoals verwezen vanuit `app.env`.)

## Belangrijke kanttekeningen

- **Huurcontracten zijn een voorbeeldsjabloon.** `contract_templates/huurovereenkomst_voorbeeld.html`
  bevat placeholder-bepalingen, geen juridisch gecontroleerde tekst. Vervang de
  inhoud door een gecontroleerd modelcontract (bijv. de modelhuurovereenkomst
  van de Rijksoverheid of Woonbond) voordat je een gegenereerd contract laat
  ondertekenen. De site zelf toont deze waarschuwing ook bij het genereren.
- **Geen automatische Kamernet-plaatsing.** De advertentieknop genereert
  alleen tekst om te kopiëren/plakken.
- **Matching op naam is een benadering.** Zonder IBAN/Zoekwoord wordt gekeken
  of de volledige naam, of anders een los naamdeel (voornaam, achternaam,
  delen van een koppelnaam), voorkomt in de afzendernaam of omschrijving -
  handig als bijvoorbeeld een ouder betaalt. Bij twijfel is een IBAN of vast
  zoekwoord per kamer betrouwbaarder.
- **Vooruitbetalingen**: er wordt ook gekeken naar betalingen die tot
  `VOORUITBETALING_DAGEN` (standaard 14) vóór de 1e van de maand binnenkomen,
  voor huurders die ruim van tevoren betalen. Als iemand wel érg vroeg in de
  vorige maand al voor de maand erna betaalt, kan dat er in de vorige maand
  even uitzien als "te veel ontvangen" - dat is onschuldig (gewoon
  vooruitbetaald), geen fout.
- **Aanzeg-waarschuwing is alleen een herinnering.** De site stuurt zelf nog
  geen aanzeggingsbrief naar de huurder - die verstuur je nog zelf. De
  waarschuwing op het dashboard/kamerpagina is puur op de einddatum in de
  sheet gebaseerd (venster: 1-3 maanden voor de einddatum).
- **Betrouwbaarheidsscore** is simpel gehouden: het percentage uitgevoerde
  controles waarbij de status "Betaald" was. Geen tracking van hoeveel dagen
  te laat, alleen of het bedrag klopte op het moment van controleren.
- **Downloaden van Google Docs/Sheets uit de Documenten-map** levert
  automatisch een PDF-export op (die bestandstypen kun je niet als los
  binair bestand downloaden) - voor al geuploade PDF's/foto's werkt
  downloaden zoals verwacht.

## Beveiliging

- `app.env`/`.env`, `google-service-account.json`, `bunq_production.conf`,
  `properties.json` en `users.json` bevatten geheimen en/of persoonsgegevens
  en staan in `.gitignore` - commit ze nooit, ook niet naar een privé-fork.
- Gebruik de Google service account en bunq API key alleen voor dit doel.
- Deel elke gebruikersinlog alleen met de betreffende persoon, en geef alleen
  toegang tot de panden die diegene ook echt nodig heeft (`--panden`, niet
  standaard `--alle-panden`).
- **Persoonsgegevens uit het aanmeldformulier** (naam, contactgegevens,
  studentnummer, inkomsten, bewijs van inschrijving) staan alleen in de Google
  Sheet ("Aanmeldingen"-tabblad) en de Drive-map van het betreffende pand -
  beide alleen bereikbaar voor ingelogde beheerders van dat pand, nooit
  publiek. Wis de aanmeldingenlijst (knop op de Aanmeldingen-pagina) zodra je
  een huurder hebt gekozen, zodat je niet onnodig lang gegevens bewaart van
  mensen die het niet zijn geworden.

## Problemen oplossen

- **`pip install` faalt op `bunq_sdk` met een `install_layout` fout** -
  verouderde `setuptools`; draai `pip install --upgrade pip setuptools wheel`
  en probeer opnieuw.
- **"Kon bunq-context bestand niet vinden"** - draai `python scripts/setup_bunq.py`
  (opnieuw, na het instellen van `BUNQ_CONF_FILE`).
- **Kamer staat op "Nog niet ontvangen" terwijl er wel betaald is** -
  controleer IBAN/naam/Zoekwoord in de sheet, en of `bunq_rekening_iban` in
  `properties.json` voor dat pand klopt.
- **Inloggen lukt niet** - controleer of `USERS_FILE` naar het juiste pad
  wijst en of `scripts/create_user.py` succesvol is gedraaid.
- **"Geen toegang" te zien terwijl dit wel zou moeten kunnen** - controleer
  `users.json`: staat `alle_panden` op `true`, of staat de juiste slug in
  `panden`?
- **Pand niet te zien in de pandkiezer/dropdown** - controleer of het pand in
  `properties.json` staat en of de gebruiker er toegang toe heeft.
