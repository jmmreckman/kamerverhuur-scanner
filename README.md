# kamerverhuur-scanner

Dagelijks (09:00) programma dat nieuwe koopwoningen in Rotterdam scant op kansen
voor kamerverhuur, en een overzicht mailt van de huizen die alle checks
doorstaan.

## Wat het doet

Elke ochtend om 09:00:

1. Leest de nieuwe Funda-listings uit je dagelijkse Funda-zoekopdracht-alert
   (via e-mail, zie hieronder — **geen scraping**, funda blokkeert dat actief). Adres,
   postcode en prijs worden uit de zichtbare tekst van de mail gehaald (funda's links
   zijn zelf ondoorzichtige clicktracking-URL's zonder bruikbare informatie erin).
2. Zoekt elk adres op via de landelijke PDOK-adressenservice op basis van
   **postcode + huisnummer** (coördinaten + wijk/buurt) — dat is ondubbelzinnig, elke
   combinatie hoort bij precies één adres in Nederland.
3. Checkt automatisch:
   - **Nul-quotumgebied** — via de officiële GIS-kaartlaag van de gemeente Rotterdam.
   - **Binnen 50 meter van een bestaande kamerverhuurvergunning** — idem.
   - **Opkoopbescherming (wijk + WOZ-waarde)** — vergelijkt de buurt met de 16 wijken
     waar opkoopbescherming geldt (bron: rotterdam.nl/opkoopbescherming) én haalt voor
     die huizen automatisch en **gratis** de WOZ-waarde op bij de officiële
     WOZ-waardeloket-API van het Kadaster (geen account, geen kosten). Dit is dus
     volledig automatisch, geen dagelijkse handmatige lijst.
4. Haalt de **officiële oppervlakte** van het BAG (Basisregistratie Adressen en
   Gebouwen) op — publieke landelijke data, vaak nauwkeuriger dan de advertentietekst.
5. Sorteert de openstaande kansen op **vraagprijs per m²** (op basis van die
   BAG-oppervlakte), niet op datum — hoe lang een huis al bekend is staat er sowieso
   al apart bij.
6. Houdt een huis maximaal **30 dagen** (`LISTING_EXPIRY_DAYS`) op de lijst en haalt
   het er daarna automatisch af. Er wordt niet gecheckt of een huis inmiddels
   verkocht/onder bod is (zie kanttekening hieronder) — je ziet zelf aan de
   "dagen bekend"-teller hoe vers een huis nog is.
7. Geeft je in het rapport per huis een **directe link naar funda** en een
   **verwijder-link** waarmee je een huis met één muisklik + versturen zelf uit de
   lijst haalt (bijv. omdat het toch niet voldoet, of gewoon niet interessant is).
8. Checkt automatisch op mogelijke **huurprijsopslagen** (WWS-puntensysteem) die de
   taxatiewaarde/huurprijs flink kunnen beïnvloeden — zie "Mogelijke huurprijsopslag"
   verderop in dit document voor de details en betrouwbaarheid per categorie.
9. Kan **niet** automatisch checken (en vraagt dit in het rapport aan jou):
   - **Zelfbewoningsplicht in de advertentietekst** — funda blokkeert geautomatiseerd
     bezoek aan advertentiepagina's (Akamai bot-detectie + verplichte CAPTCHA), dus dit
     vraagt het rapport je de advertentietekst zelf even (10 sec) door te lezen. Dit
     staat bij elk overgebleven huis, maar dat zijn er dankzij de eerdere checks nog
     maar een handjevol per dag.
   - **Provinciaal monument** (15% huurprijsopslag) — geen bevraagbare open data
     gevonden bij de provincie; komt in Rotterdam bovendien vrijwel nooit voor.
10. Mailt een dagoverzicht naar `jmmreckman@gmail.com` met alle nog openstaande
    kansen, hoe lang ze al bekend zijn, en welke (weinige) handmatige check nog nodig is.

**Over "verkocht"/"onder bod":** funda's dagelijkse zoekopdracht-alert meldt alleen
NIEUWE woningen, nooit dat een eerder geziene woning van status is veranderd. Funda
heeft daar wel een aparte functie voor (de "favorieten-e-mail", met per-huis
favoriet-markeren), maar dat vereist een handmatige klik per huis op funda.nl zelf —
bewust niet gekozen, want dat schaalt niet als je dagelijks meerdere kandidaten
krijgt. In plaats daarvan: een huis blijft gewoon (tot max. 30 dagen) op de lijst
staan, en jij gebruikt de "dagen bekend"-teller en je eigen inschatting om te bepalen
of iets nog vers genoeg is, of klikt het er zelf uit met de verwijder-link.

**Waarom niet alles automatisch?** Funda draait achter actieve bot-detectie (Akamai +
verplichte Google reCAPTCHA) en verbiedt geautomatiseerd bezoek in de voorwaarden. Dit
programma omzeilt dat bewust niet — dat zou dagelijks CAPTCHA's moeten kraken en je
account/IP kunnen laten blokkeren. De WOZ-waarde is een ander verhaal: sinds de Wet
WOZ in 2022 is aangepast, is de WOZ-waarde van woningen wettelijk openbare informatie,
en het Kadaster ontsluit die zelf gratis via wozwaardeloket.nl. Dit programma bevraagt
dezelfde achterliggende API die die website gebruikt, één adres tegelijk — net als een
mens die het adres intypt, alleen dan geautomatiseerd voor de paar huizen per dag die
in een opkoopbeschermde wijk liggen. Geen key, geen kosten, geen bot-omzeiling nodig
(dit endpoint gaf gewoon nette JSON terug, geen CAPTCHA — het is alleen niet als
officiële developer-API gedocumenteerd, zie "Bekende beperkingen"). Alleen de
zelfbewoningsplicht-tekstcheck blijft (noodgedwongen) een korte handmatige stap.

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

"Openstaande kansen" is gesorteerd op **vraagprijs per m² (laagste eerst)**, op basis
van de officiële BAG-oppervlakte. Elke rij toont:

- **Adres, wijk, vraagprijs, oppervlakte** (`... m² (BAG)`, de officiële maat, niet de
  advertentietekst) **en €/m²** — als de prijs een keer niet herkend kon worden uit de
  alertmail, staat het huis onderaan (zie "Bekende beperkingen").
- **Dagen bekend** — dagen sinds dit systeem het huis voor het eerst zag via je
  Funda-alertmail. In de praktijk vrijwel altijd gelijk aan de echte
  "in verkoop sinds"-datum (funda's alert gaat elke nacht uit), maar geen harde
  garantie. Gebruik dit als indicatie: hoe langer een huis erop staat zonder dat jij
  het verwijderd hebt, hoe groter de kans dat het (bijna) verkocht is.
- **Badges** met wat je zelf nog moet checken:
  - `check WOZ-waarde` — verschijnt normaal NIET: de WOZ-waarde wordt automatisch en
    gratis gecheckt (boven de grens, standaard €470.000 en aanpasbaar via
    `OPKOOPBESCHERMING_WOZ_GRENS`, valt het huis niet af). De badge duikt alleen op
    als de opvraging een keer mislukte of geen data teruggaf — kijk dan naar de
    opmerking eronder voor de reden.
  - `check zelfbewoningsplicht` — staat altijd, want dit kan niet automatisch.
    Open de link en zoek (Ctrl+F) op "zelfbewoning".
- **Mogelijke huurprijsopslag** — automatische check op signalen die de WWS-huurprijs
  (en daarmee de taxatiewaarde) flink kunnen beïnvloeden:
  - **Rijksmonument (35%)** en **rijksbeschermd stads-/dorpsgezicht (5%, alleen als het
    pand van vóór 1965 is en geen andere monumentenopslag krijgt)** — via de officiële,
    gratis kaartendata van de Rijksdienst voor het Cultureel Erfgoed (RCE). Betrouwbaar,
    maar altijd gemarkeerd als "mogelijk": rijksmonument-posities zijn soms niet
    pixel-precies, dus verifieer altijd via de meegestuurde link naar het officiële
    monumentenregister voordat je erop rekent.
  - **Nieuwbouwopslag (10%)** — op basis van het officiële BAG-bouwjaar (opgeleverd na
    1 juli 2024). Betrouwbaar qua bouwjaar zelf; of de opslag ook echt van toepassing is
    (reguliere, niet-monumentale middenhuur, bouw gestart vóór 2028) moet je zelf
    beoordelen.
  - **Gemeentelijk monument (15%)** — Rotterdam heeft geen bevraagbare open data voor
    zijn eigen monumentenregister (het is een interactieve webapplicatie zonder
    open-data-koppeling), dus dit gebruikt een door een derde gepubliceerde kopie van
    een Rotterdamse monumentenlijst uit 2021. **Minder betrouwbaar** dan de andere
    checks — mogelijk verouderd of onvolledig. Áltijd verifiëren op
    [monumentenregister.rotterdam.nl](https://monumentenregister.rotterdam.nl/) voordat
    je hierop rekent.
  - **Provinciaal monument (15%)** — wordt niet automatisch gecheckt: de provincie
    ontsluit dit alleen als kaartplaatje (WMS), niet als bevraagbare data, en dit komt
    in Rotterdam vrijwel nooit voor. Check dit zelf als het relevant lijkt.
  - Staat er niets bij een huis, dan betekent dat alleen dat de automatische checks
    niets vonden — geen garantie dat er zeker geen opslag van toepassing is (met name
    voor gemeentelijk/provinciaal monument).
- **Acties**:
  - **Bekijk advertentie →** — directe link naar de advertentie. Bij woningen uit de
    dagelijkse Funda-mail is dit een echte link naar de advertentie zelf; bij handmatig
    toegevoegde adressen zonder link is het een zoeklink (Google) op basis van het adres,
    omdat Funda's eigen postcode-zoek-URL ongedocumenteerd en onbetrouwbaar bleek.
  - **Verwijderen** — opent een kant-en-klare e-mail naar je scanner-mailbox met als
    onderwerp "Verwijder <postcode-huisnummer>" (bijv. "Verwijder 3073KJ-47A"). Gewoon
    versturen (niets aanpassen); bij de volgende dagelijkse run wordt het huis eruit
    gehaald en verschijnt het onder "Handmatig verwijderd" in plaats van
    "Openstaande kansen".

Huizen die automatisch afvielen op het nul-quotumgebied of de 50-meter-check
verdwijnen niet stil: ze staan (voor de dag waarop ze gevonden zijn) in de sectie
"Vandaag afgevallen op geo-checks", met reden — zo kun je fouten in de checks zelf
opmerken.

Een huis verdwijnt automatisch uit "Openstaande kansen" als het 30 dagen
(`LISTING_EXPIRY_DAYS`) niet meer in een nieuwe alertmail is opgedoken, of eerder als
jij het zelf met de verwijder-link weghaalt. Er is bewust geen automatische
verkocht/onder-bod-detectie (zie hierboven) — dat is een bewuste keuze om geen
handmatige klik per huis op funda.nl nodig te hebben.

## Achterstand inhalen / zelf gevonden huizen toevoegen

De dagelijkse Funda-alert meldt alleen NIEUWE woningen vanaf het moment dat je de
zoekopdracht instelt — huizen die al langer te koop stonden, of huizen die je zelf
tegenkomt tijdens het bladeren op funda.nl, komen er niet vanzelf in. Daarvoor is er
`handmatig_toevoegen.py`: je zet zelf (handmatig, gewoon browsend — geen scraping)
adressen in een tekstbestand, en het script haalt ze door dezelfde checks als de
dagelijkse run en stuurt er direct een rapport-mail van.

```powershell
copy adressen.voorbeeld.txt adressen.txt
notepad adressen.txt
venv\Scripts\python handmatig_toevoegen.py adressen.txt
```

Twee bestandsformaten worden automatisch herkend (je hoeft niet aan te geven welke):

**1. Eén adres per regel** — `POSTCODE HUISNUMMER[TOEVOEGING] [funda-link]`:

```
3073KJ 47A
3078CN 44 https://www.funda.nl/detail/koop/rotterdam/huis-vredehagen-44/12345678/
```

De funda-link is optioneel (zonder link krijg je in het rapport een zoeklink op basis
van het adres — Funda's eigen postcode-zoek-URL bleek onbetrouwbaar). Regels die met
`#` beginnen worden overgeslagen.

**2. Een ruwe kopieer-plak van een funda-zoekresultatenpagina** — selecteer in je
browser de hele resultatenlijst (Ctrl+A op de pagina, of sleep-selecteren), kopieer
(Ctrl+C), en plak in een tekstbestand. Dat levert rommelige tekst op (adres, postcode,
prijs, oppervlaktes, kamers, energielabel, makelaarsnaam, badges als "Blikvanger" of
"Nieuw" — allemaal op losse regels, met een wisselend aantal regels per woning) maar
dat hoeft niet netter: het script herkent adres, postcode/plaats en vraagprijs
er zelf automatisch uit, en negeert de rest. Dit is de snelste manier om in één keer
een groot deel van het huidige aanbod te verwerken. Nogmaals: dit is geen scraping —
jij bekijkt en kopieert de pagina zelf in je eigen browser, het script leest alleen de
tekst die je al hebt gekopieerd.

Bij grote bestanden (honderden adressen) duurt het verwerken een tijdje (elk adres
kost een paar seconden aan controles) — reken op zo'n 15-20 minuten voor een paar
honderd adressen. Dat is prima voor een eenmalige inhaalslag; laat het gewoon draaien.

Vanaf het moment dat een huis verwerkt is staat het in `state.json` en loopt het
automatisch mee in elke volgende dagelijkse run (30-dagen-expiry, verwijder-link,
alles hetzelfde als voor huizen die via de e-mail-alert binnenkomen). Een adres dat al
eerder verwerkt is, wordt bij een volgende run alleen ververst (url/prijs) en niet
opnieuw door de checks gehaald — voeg `--herprocessen` toe om dat wel te doen (bijv.
na een bugfix in een van de checks):

```powershell
venv\Scripts\python handmatig_toevoegen.py adressen.txt --herprocessen
```

Handmatig verwijderde adressen (via de verwijder-link) worden hierbij nooit opnieuw
actief, ook niet als de checks ze nu zouden goedkeuren.

**"Dagen bekend" bij de inhaalslag:** funda toont op de zoekresultatenpagina vaak
"Sinds X weken/maanden" of een exacte datum bij een woning — de tekstdump-parser
herkent dat en gebruikt het als startpunt voor de "dagen bekend"-teller, in plaats
van gewoon "vandaag" voor alles. Staat er geen datum-aanduiding bij een huis, dan
wordt het toch "vandaag" (dag 1 van 30). Dit heeft geen invloed op de 30-dagen-expiry
zelf — die kijkt naar wanneer dit systeem een huis voor het laatst zag, niet naar hoe
oud de advertentie is — dus een huis dat al een jaar te koop staat valt niet meteen
weg omdat de datum ver in het verleden ligt.

## Databronnen (en waarom ze robuust genoeg zijn om op te bouwen)

- **Adressen/coördinaten/wijk**: PDOK Locatieserver (`api.pdok.nl`) — landelijke,
  publieke, voor geautomatiseerd gebruik bedoelde overheids-API. Bevraagd op
  postcode + huisnummer (uit de Funda-mail-tekst), niet op straatnaam.
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
- **WOZ-waarde per adres**: de gratis, officiële WOZ-waardeloket-API van het Kadaster
  (`api.kadaster.nl/lvwoz`) — dezelfde die wozwaardeloket.nl zelf gebruikt, WOZ-waarden
  van woningen zijn sinds 2022 wettelijk openbare informatie. Bevraagd op
  BAG-nummeraanduiding-ID (uit de PDOK-geocode), niet op vrije tekst, dus
  ondubbelzinnig. Elk adres wordt maar één keer bevraagd (het resultaat blijft in
  `data/state.json` staan); geeft de opvraging een keer geen data (storing, of een
  niet-woonfunctie zonder openbare WOZ-waarde), dan valt dit terug op een handmatige
  melding in het rapport.
- **Officiële oppervlakte**: de publieke PDOK BAG-WFS (`service.pdok.nl/lv/bag`) —
  landelijke basisregistratie, geen API-key nodig, bevraagd op het BAG-verblijfsobject-ID
  (uit de PDOK-geocode). Dit is de "echte" maat, die geregeld afwijkt van wat in een
  advertentie staat.
- **Adres/postcode/prijs/Funda-listings**: uit de zichtbare tekst van je eigen
  Funda-alertmail, geen scraping. Funda's links zelf zijn clicktracking-URL's
  (`links.funda.nl`, via Iterable) zonder herleidbare informatie — die gebruiken we
  alleen als kant-en-klare klik-link in het rapport, niet om data uit te halen.
- **Verwijder-commando's**: mails die jijzelf (via de verwijder-link in het rapport)
  naar je scanner-mailbox stuurt, met "Verwijder <postcode-huisnummer>" in het
  onderwerp.
- **Rijksmonumenten & rijksbeschermde stads-/dorpsgezichten**: de gratis, publieke
  WFS-kaartendata van de Rijksdienst voor het Cultureel Erfgoed
  (`services.rce.geovoorziening.nl/rce/wfs`) — officiële landelijke overheidsdata,
  bevraagd op coördinaat (rijksmonument-puntlocaties met een kleine zoekstraal, want
  die zijn soms niet pixel-precies; beschermde-stadsgezicht-gebieden met een exacte
  polygon-intersectie).
- **Bouwjaar** (voor nieuwbouwopslag en de bouwjaar-voorwaarde bij beschermd
  stadsgezicht): dezelfde publieke PDOK BAG-WFS-opvraging als de oppervlakte, geen
  extra netwerkcall nodig.
- **Gemeentelijke monumenten (Rotterdam)**: geen officiële bevraagbare bron gevonden
  (monumentenregister.rotterdam.nl is een interactieve webapplicatie zonder
  open-data-koppeling) — dit gebruikt een door een derde op ArcGIS Online gepubliceerde
  kopie van een Rotterdamse monumentenlijst uit 2021. Minder betrouwbaar dan de andere
  databronnen in dit project; altijd als "mogelijk" gepresenteerd met een link naar het
  officiële register om zelf te verifiëren.

## Bekende beperkingen

- **Adres- en prijsherkenning zijn afhankelijk van funda's huidige e-mail-opmaak.**
  Funda's links zijn clicktracking-URL's zonder bruikbare informatie, dus adres,
  postcode en prijs worden uit de zichtbare tekst rond elke woning-link gehaald
  (getest tegen een echte alertmail, zie `tests/test_funda_mail.py`). Verandert
  funda die opmaak drastisch, dan kan de parser huizen missen of prijzen niet
  herkennen — dit crasht niet: onherkende adressen belanden in "Kon niet automatisch
  verwerkt worden" met de kale link, en er komt een waarschuwing in het rapport als
  het aantal herkende woningen niet overeenkomt met wat funda's "Bekijk alle N
  woningen"-knoppen aankondigen. Werkt de herkenning een keer niet goed, gebruik dan
  `tools/test_email_parsing.py` tegen een opgeslagen `.eml` om te zien wat er
  wel/niet herkend wordt, en stel zo nodig de patronen in
  `rotterdam_scanner/funda_mail.py` bij.
- **Als funda op één dag meer nieuwe woningen vindt dan er individueel in de mail
  passen** (de mail toont blijkbaar niet altijd alles los, met een "Bekijk alle N
  woningen"-knop voor de rest — dat leidt naar een zoekresultatenpagina die we niet
  kunnen openen), mist het systeem die extra woningen. Het rapport waarschuwt hierover
  als het detecteerbaar is. Voorkomen: zet liever een paar smallere zoekopdrachten op
  dan één hele brede, zodat je zelden meer dan een paar nieuwe woningen per opdracht
  per dag hebt.
- **Geen automatische verkocht/onder-bod-detectie** (bewuste keuze, zie hierboven) —
  een verkocht huis blijft tot max. 30 dagen op de lijst staan tenzij je het zelf met
  de verwijder-link weghaalt.
- De verwijder-link werkt met een simpel patroon (mail met "Verwijder <id>" in het
  onderwerp naar je eigen scanner-mailbox); er zit geen afzender-verificatie op, wat
  bij een privé-mailbox die alleen jij en dit systeem gebruiken een verwaarloosbaar
  risico is (in het ergste geval verdwijnt een huis onterecht, wat je zelf opmerkt).
- Geocoding via PDOK werkt op basis van postcode + huisnummer(+toevoeging), rechtstreeks
  uit de Funda-mail-tekst of het handmatige adressenbestand gehaald (huisnummer en
  toevoeging worden met een koppelteken samengevoegd in de zoekopdracht, bijv.
  "184-02L" — nodig omdat PDOK toevoegingen die met een cijfer beginnen zonder dat
  koppelteken soms stilzwijgend fout matcht). Bij zeer ongebruikelijke
  huisnummer-schrijfwijzen kan het alsnog misgaan. Ook dan: geen crash, wel een
  duidelijke melding in het rapport.
- De tekstdump-parser voor `handmatig_toevoegen.py` herkent adressen aan de hand van
  de postcode-regel (heel herkenbaar patroon) en pakt de regel erboven als adres —
  getest tegen een echte kopieer-plak van 410 funda-resultaten zonder fouten, maar
  blijft, net als de e-mail-parser, afhankelijk van hoe funda haar pagina's opbouwt.
- De "dagen bekend"-teller is gebaseerd op wanneer dit systeem het huis zag, niet
  op een officiële funda-datum.
- **De WOZ-waarde-endpoint is niet als publieke developer-API gedocumenteerd** — het
  is teruggevonden in de broncode van wozwaardeloket.nl zelf, niet iets met een
  stabiliteitsgarantie van het Kadaster. Hij werkt betrouwbaar en geeft nette
  foutcodes (geen bot-geweer), maar kan in theorie ooit veranderen. Gaat dat gebeuren,
  dan valt de opkoopbescherming-check automatisch terug op de handmatige
  "check WOZ-waarde"-melding in het rapport (geen crash) — check in dat geval
  `rotterdam_scanner/woz.py`.

## Ontwikkelen / tests

```powershell
venv\Scripts\pip install pytest
venv\Scripts\python -m pytest
```
