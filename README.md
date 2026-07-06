# kamerverhuur-scanner

Controleert automatisch of de huur van je studentenkamers is binnengekomen en
of het bedrag klopt, door je bunq-rekening te vergelijken met een Google Sheet
met huurdersgegevens. Stuurt daarna een rapportage per e-mail (via Gmail) en
werkt de sheet bij met de status per huurder.

Bedoeld om een paar keer per maand via een cronjob te draaien op je eigen pc
(bijvoorbeeld op de 1e, 3e en 5e van de maand).

## Wat het script doet

1. Leest de huurderslijst (naam, kamer, verwacht bedrag, IBAN/zoekwoord) uit een Google Sheet.
2. Haalt via de bunq API alle inkomende betalingen van deze maand op.
3. Koppelt elke betaling aan de juiste huurder (op IBAN, of anders op naam/zoekwoord).
4. Bepaalt per huurder de status: **Betaald** / **Te weinig ontvangen** / **Te veel ontvangen** / **Nog niet ontvangen**.
5. Schrijft die status + het ontvangen bedrag terug in de sheet.
6. Mailt een overzicht naar jezelf, met de aandachtspunten bovenaan.

## Verwachte kolomindeling in de Google Sheet

Tabblad (standaard genaamd `Huurders`), rij 1 = koppen, data vanaf rij 2:

| A Naam | B Kamer | C Verwacht bedrag | D IBAN (optioneel) | E Zoekwoord (optioneel) | F Status | G Ontvangen bedrag | H Laatst gecontroleerd |
|---|---|---|---|---|---|---|---|
| Jan de Vries | 1 | 650,00 | NL91ABNA0417164300 | | | | |
| Fatima El Idrissi | 2 | 625,00 | | kamer2 | | | |

- Kolom **A t/m E** vul jij in en pas je zelf aan (namen, kamers, bedragen).
- Kolom **F, G, H** worden door het script overschreven bij elke run — daar hoef je niets in te typen.
- **IBAN** is de betrouwbaarste matching-methode: als die is ingevuld, wordt er alleen op IBAN gematcht.
- Zonder IBAN wordt gematcht op **Zoekwoord** (bijv. een vaste omschrijving die de huurder gebruikt) of anders op de **naam** van de huurder (met een fallback op de achternaam, voor het geval de bank een afgekorte naam toont).
- 15 rijen invullen is genoeg, maar het werkt met elk aantal.

## Vereisten

- Python 3.10 of hoger op de pc waar je het script draait (je "zolder-pc").
- Een Google-account met een Google Sheet.
- Een bunq-rekening en de bunq-app (voor de API key).
- Een Gmail-adres met een **app-wachtwoord** (heb je al).

## Stap 1: Google Sheet aanmaken

Maak een nieuwe Google Sheet aan met een tabblad `Huurders` en de kolommen hierboven.
Onthoud het **sheet ID**: het stuk uit de URL tussen `/d/` en `/edit`:

```
https://docs.google.com/spreadsheets/d/DIT_IS_HET_SHEET_ID/edit
```

## Stap 2: Google service account aanmaken (voor API-toegang)

1. Ga naar [Google Cloud Console](https://console.cloud.google.com/) en maak een (nieuw) project.
2. Ga naar **APIs & Services > Library**, zoek **Google Sheets API** en klik op **Enable**.
3. Ga naar **APIs & Services > Credentials > Create Credentials > Service account**.
   Geef 'm een naam (bijv. "kamerverhuur-scanner") en klik 'm af (rollen zijn niet nodig).
4. Open het aangemaakte service account, ga naar het tabblad **Keys > Add Key > Create new key**, kies **JSON**.
   Er wordt een JSON-bestand gedownload.
5. Hernoem dit bestand naar `google-service-account.json` en zet het in de projectmap
   (of een ander pad, dan pas je `GOOGLE_SERVICE_ACCOUNT_FILE` in `.env` aan).
   **Dit bestand nooit committen** — het staat al in `.gitignore`.
6. Open het JSON-bestand en kopieer het `client_email` adres (iets als
   `kamerverhuur-scanner@jouwproject.iam.gserviceaccount.com`).
7. Open je Google Sheet, klik **Delen**, en deel de sheet met dat e-mailadres als **Bewerker**.
   Zonder deze stap kan het script de sheet niet lezen of bijwerken.

## Stap 3: bunq API key aanmaken

1. Open de bunq-app > **Profiel > Instellingen > Developers/API keys** (of vergelijkbaar) > nieuwe API key aanmaken.
2. Kies bij de IP-restrictie **"Alle IP-adressen toestaan"**, tenzij je thuis een vast IP-adres hebt.
   De meeste consumentenverbindingen hebben een wisselend IP; met een vaste IP-restrictie loop je het risico dat de cronjob stuk gaat als je IP verandert. De extra beveiliging is beperkt, omdat de key pas echt bruikbaar wordt in combinatie met de privésleutel die hieronder lokaal wordt aangemaakt.
3. Wijs de key binnen 4 uur toe (anders vervalt hij), en kopieer de key-waarde.
4. Zet die waarde in je `.env` bestand als `BUNQ_API_KEY` (zie Stap 5).
5. Draai daarna **eenmalig**:

   ```bash
   python scripts/setup_bunq.py
   ```

   Dit registreert je pc als "device" bij bunq en slaat de sessie + het bijbehorende
   sleutelpaar lokaal op in het bestand uit `BUNQ_CONF_FILE` (standaard `bunq_production.conf`).
   Dit hoef je niet te herhalen bij elke run — alleen als je dit bestand kwijtraakt
   of de koppeling bij bunq intrekt. **Committen mag niet** (staat in `.gitignore`).

> **Let op:** bunq heeft de officiële Python SDK (`bunq_sdk`, gebruikt in dit project) gemarkeerd
> als niet langer actief onderhouden. Hij werkt op dit moment nog prima voor dit doel, maar mocht
> bunq de API ooit op een incompatibele manier wijzigen, dan kan `scripts/setup_bunq.py` of
> `kamerverhuur_scanner/bunq_client.py` aangepast moeten worden. Zie https://doc.bunq.com voor de actuele documentatie.

## Stap 4: Gmail app-wachtwoord

Je hebt al een Gmail-adres met app-wachtwoord. Zet in `.env`:

- `GMAIL_ADDRESS` — het Gmail-adres waarmee verstuurd wordt.
- `GMAIL_APP_PASSWORD` — het app-wachtwoord (16 tekens, zonder spaties).
- `EMAIL_TO` — het adres waar de rapportage naartoe moet (mag hetzelfde zijn).

## Stap 5: installeren

```bash
git clone <deze-repo>
cd kamerverhuur-scanner
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# vul .env in met een editor (sheet ID, bunq key, gmail app-wachtwoord, etc.)

python scripts/setup_bunq.py     # eenmalig, zie Stap 3
```

## Stap 6: testen

Draai eerst een dry-run: dit print het rapport op het scherm, maar verstuurt
geen mail en wijzigt de sheet niet:

```bash
python main.py --dry-run
```

Klopt het overzicht? Draai 'm dan zonder `--dry-run` voor een echte run
(sheet bijwerken + mail versturen):

```bash
python main.py
```

## Stap 7: automatisch laten draaien op de 1e, 3e en 5e van de maand

### Linux/macOS (cron)

Open je crontab:

```bash
crontab -e
```

Voeg toe (past aan `/pad/naar/kamerverhuur-scanner` en het venv-pad):

```
0 9 1,3,5 * * cd /pad/naar/kamerverhuur-scanner && /pad/naar/kamerverhuur-scanner/.venv/bin/python main.py >> /pad/naar/kamerverhuur-scanner/cron.log 2>&1
```

Dit draait elke 1e, 3e en 5e dag van de maand om 09:00. Pas het tijdstip aan naar wens.

### Windows (Taakplanner)

1. Open **Taakplanner** > **Basistaak maken**.
2. Trigger: **Maandelijks**, dagen **1, 3, 5**.
3. Actie: **Programma starten**, programma `C:\pad\naar\.venv\Scripts\python.exe`,
   argumenten `main.py`, starten in `C:\pad\naar\kamerverhuur-scanner`.

## Beveiliging

- `.env`, `google-service-account.json` en `bunq_production.conf` bevatten geheimen
  en staan in `.gitignore` — commit ze nooit.
- Gebruik de Google service account en bunq API key **alleen** voor dit script.
- Het rapport bevat financiële gegevens; zorg dat `EMAIL_TO` een adres is dat alleen jij leest.

## Beperkingen

- Er wordt per bunq-rekening naar de meest recente 200 transacties gekeken (ruim
  voldoende voor 15 huurders per maand, maar geen volledige historie).
- Matching op naam is een benadering (substring-vergelijking); bij twijfel is een
  IBAN of vast zoekwoord per huurder betrouwbaarder.
- Een betaling wordt aan maximaal één huurder toegekend (op volgorde van de sheet),
  zodat bedragen niet dubbel meetellen.

## Problemen oplossen

- **`pip install` faalt op `bunq_sdk` met een `install_layout` fout** — dit komt door
  een verouderde `setuptools`. Draai eerst `pip install --upgrade pip setuptools wheel`
  in je virtualenv en probeer het opnieuw.
- **"Kon bunq-context bestand niet vinden"** — draai `python scripts/setup_bunq.py` eenmalig.
- **Huurder staat op "Nog niet ontvangen" terwijl er wel betaald is** — controleer of
  de naam/IBAN in de sheet overeenkomt met de bankgegevens, of vul de kolom Zoekwoord in.
- **E-mail komt niet aan** — controleer `GMAIL_APP_PASSWORD` (geen gewoon Gmail-wachtwoord)
  en of "minder veilige apps"/app-wachtwoorden nog actief zijn op het Google-account.
