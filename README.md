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
- **Wissel van pand (dropdown in de navigatie)** - blijft zoveel mogelijk op
  dezelfde (soort) pagina staan voor het andere pand (bv. van Kamers bij
  pand A naar Kamers bij pand B, i.p.v. terug te vallen op het dashboard).
  Sta je op een detailpagina die niet 1-op-1 bestaat bij het andere pand
  (bv. een specifieke kamer of contract), dan land je op de overzichtspagina
  van diezelfde sectie. Bij "Pand bewerken" wissel je naar het bewerkscherm
  van het andere pand.
- **Toegangscontrole per pand** - probeer je bij een pand te komen waar je geen
  toegang toe hebt, dan krijg je een duidelijke melding ("geen toegang, vraag de
  beheerder") in plaats van een foutmelding.
- **Gebruikersbeheer** - gebruikers met toegang tot alle panden zien een
  "Gebruikers"-knop in de site zelf, waar nieuwe collega's/mede-eigenaren
  toegevoegd kunnen worden en per gebruiker aan te vinken is bij welke panden
  diegene mag (of "alle panden"). Geen command line meer voor nodig na de
  eerste installatie.
- **Panden beheren** - nieuwe panden toevoegen, bewerken of verwijderen kan
  via de "Panden"-knop in de site zelf (voor beheerders met toegang tot alle
  panden) - geen `properties.json` meer met de hand bewerken op de server.
- **Dashboard** - tegels per pand: "X/Y huurpenningen ontvangen" en het
  ontvangen bedrag (allebei linken naar de Betalingen-pagina), per kamer die
  binnenkort (binnen ~2 maanden) leegkomt een eigen tegel ("Binnen X weken
  komt kamer Y leeg"), en snelkoppelingen naar "Mail het hele huishouden" en
  "Huuropzegging doorgeven". Daarboven staat, indien van toepassing, een
  aparte waarschuwing als een tijdelijk huurcontract binnenkort (of al)
  aangezegd moet worden (wettelijk verplicht 1-3 maanden voor de einddatum,
  art. 7:271 BW) - eenmaal aangezegd kun je die waarschuwing wegklikken
  ("Afgehandeld"); ze verdwijnt dan totdat er een nieuw contract met een
  andere einddatum voor die kamer is. De "komt leeg"-tegel blijft daarna
  gewoon staan (aangezegd hebben betekent niet dat de kamer al weer verhuurd
  is) - die verdwijnt vanzelf zodra de kamer een nieuwe huurder (en dus een
  nieuwe einddatum) heeft.
- **Huuropzegging doorgeven** - knop op het dashboard: kies een huurder uit een
  dropdown, geef de nieuwe einddatum op en sla op. Die einddatum wordt direct
  weggeschreven naar kolom F ("Contract einddatum") van de Huurders-sheet -
  precies dezelfde kolom die de aanzeg-waarschuwing en de "komt leeg"-tegel al
  gebruiken, dus die reageren er automatisch op. De rest van de kamergegevens
  (huurprijs, contactgegevens, contractvelden) blijft ongewijzigd.
- **Kamers** - overzicht van alle kamers van het gekozen pand, klik door naar een
  kamer voor huurder, huurprijs, contract(en), betaalgeschiedenis en een
  betrouwbaarheidsscore (% van de controles op tijd/correct betaald). De
  lopende kalendermaand staat vanaf de 1e gewoon in die lijst (op basis van
  de laatste "Nu controleren"-uitkomst), ook al is de Historie-sheet zelf nog
  niet bijgewerkt.
- **Huurders** - toont en bewerkt de kamer-/huurdersgegevens (Google Sheet blijft
  de opslag op de achtergrond, maar bewerken kan gewoon op de site - geen aparte
  Google-toegang nodig voor medegebruikers).
- **Betalingen** - toont eerst het overzicht wie wel/niet betaald heeft, met de
  actieknoppen (herinnering/ingebrekestelling) per rij; de "Nu controleren"-
  en "Betaalgeschiedenis aanvullen"-knoppen staan daaronder. Op mobiel wordt
  de tabel geen brede tabel om horizontaal te scrollen, maar een gestapelde
  lijst (elke rij een kaartje met labels) die past op het scherm. "Nu
  controleren" haalt inkomende betalingen van bunq op (alleen van de
  bunq-rekening die bij dat pand hoort), koppelt ze aan de huurders, toont
  het resultaat, en schrijft de sheet + geschiedenis bij.
- **Dagelijkse automatische controle** - draait daarnaast elke ochtend om
  06:00 (Nederlandse tijd) vanzelf dezelfde controle voor alle panden, zodat
  de lijst altijd up-to-date is zonder dat er iemand op de knop hoeft te
  drukken (zie `scripts/dagelijkse_controle.py` en de `dagelijkse-check`-
  service in `deploy/docker-compose.yml`). Draait ook meteen één keer bij het
  opstarten van de container (dus ook na elke nieuwe deploy), zodat een
  herstart de 06:00-controle nooit per ongeluk overslaat. De "Nu
  controleren"-knop blijft gewoon werken voor tussendoor. Zodra alle kamers
  van een pand voor de huidige maand "Betaald" staan, gaat er - eenmalig die
  maand - een mailtje naar de beheerder(s) (`EMAIL_BCC` + eventuele
  pand-specifieke "Extra BCC") met de melding dat de huur compleet binnen is.
  Geen SMTP ingesteld? Dan wordt die melding gewoon overgeslagen (de rest van
  de controle werkt door). Lukt het wegschrijven van de Historie-sheet een
  keer niet (bv. een tijdelijke Google Sheets-hapering), dan wordt dat alleen
  gelogd - de actuele status blijft gewoon bijgewerkt, en de lopende maand
  verschijnt dan alsnog in de betaalgeschiedenis op de kamerpagina (zie
  hieronder).
- **Betaalgeschiedenis aanvullen** - knop op de Betalingen-pagina die de
  betaalgeschiedenis ophaalt bij bunq en per maand een Historie-regel
  wegschrijft, op basis van de huidige huurderslijst. **Per kamer**: heeft die
  kamer een bekende **"Contract startdatum"** (kolom X)? Dan wordt teruggezocht
  vanaf díe instapmaand - geen jaar aan "Nog niet ontvangen" meer voor maanden
  van vóórdat de huurder er woonde. Geen bekende startdatum? Dan geldt de
  standaard van 12 kalendermaanden terug (aanpasbaar via `aantal_maanden` in
  `backfill_geschiedenis()` - bunq zelf legt geen harde limiet op hoe ver terug
  je kunt ophalen, zolang de rekening bestaat). Elke maand wordt onafhankelijk
  beoordeeld op basis van wat er die kalendermaand ECHT is binnengekomen
  (vergeleken met het HUIDIGE verwachte bedrag - de sheet houdt geen
  historische huurbedragen bij, dus rond een huurverhoging kunnen oudere
  maanden om die reden "Te weinig" tonen, ook al was er op dat moment gewoon
  correct betaald tegen het toen geldende bedrag).
  **Instapmaand:** in de kalendermaand van de "Contract startdatum" wordt niet
  de volle maandhuur verwacht, maar de **pro-rata huur** over de resterende
  dagen van die maand (bij een start op de 1e is dat gewoon de volle
  maandhuur) **plus de waarborgsom** uit kolom Y ("Borg") - huurders betalen
  die vaak in één keer samen met de eerste (deel)maand, en dat mag niet als
  "Te veel ontvangen" verschijnen. Voor de instapmaand geldt bovendien een
  ruimere tolerantie van **10%** i.p.v. de normale (bijna exacte) tolerantie
  in centen - de pro-rata berekening wijkt vaker een paar euro af door
  afrondingsverschillen (bv. een dag verschil in de ingangsdatum), en borg +
  eerste huur worden ook vaak in 2 losse overschrijvingen betaald in plaats
  van 1. Zie ook "Welke maand telt een betaling mee" hieronder voor de
  1e/17e/18e-regel die ná de instapmaand blijft gelden.
  Ruimt bij elke druk op de knop ook automatisch eventuele dubbele
  Historie-regels voor dezelfde (kamer, maand)-combinatie op, én (voor kamers
  met een bekende "Contract startdatum") regels van vóór die instapdatum die
  door een eerdere run per ongeluk waren weggeschreven - bv. toen de
  startdatum nog niet in een herkend formaat stond. Regels van een vorige
  huurder op diezelfde kamer blijven daarbij gewoon staan. Je hoeft dus nooit
  zelf met de hand in de sheet op te ruimen.
- **Betaalherinnering / ingebrekestelling** - bij elke kamer die niet
  "Betaald" staat, verschijnen op de Betalingen-pagina twee knoppen: "Stuur
  herinnering" (vriendelijke betaalherinnering) en "Stuur ingebrekestelling"
  (formele aanmaning met een betaaltermijn). De site stelt de e-mail zelf op
  (met bedrag, kamer en pandnaam) en toont 'm op een voorbeeldscherm waar je
  onderwerp/tekst nog kunt aanpassen voordat je 'm verstuurt. De mail gaat
  naar het e-mailadres van de huurder (kolom P), met een BCC naar de
  adressen in `EMAIL_BCC` (plus eventuele pand-specifieke "Extra BCC"). Die
  BCC-adressen staan ook meteen als Reply-To in de mail - antwoordt de
  huurder erop, dan komt dat rechtstreeks bij jou (en eventuele mede-
  eigenaren) terecht, in plaats van alleen in de info@-mailbox die niemand
  dagelijks in de gaten houdt. Vereist eenmalig SMTP-instellingen in `.env`
  (zie Stap 2b) - zonder die instellingen krijg je een duidelijke
  foutmelding in plaats van een crash. Zodra een mail écht is verstuurd (niet al bij het
  klikken op de knop, pas ná een geslaagde verzending) verschijnt er een
  groen "Verzonden"-vinkje naast de betreffende knop, zodat in één oogopslag
  duidelijk is of je die huurder deze maand al benaderd hebt. Dat vinkje
  reset vanzelf zodra er een nieuwe kalendermaand begint.
- **Mail het hele huishouden** - knop op de Huurders-pagina om alle huidige
  huurders van dat pand in één keer aan te schrijven (bv. "de taxateur komt
  langs", "we zijn bekend met de lekkage"). Je typt onderwerp/tekst op de
  site; elke huurder krijgt een eigen, losse mail (ze zien elkaars adres
  niet), met dezelfde BCC/Reply-To-instelling als de betaalherinneringen.
  Huurders zonder bekend e-mailadres worden overgeslagen, met een melding
  wie dat waren.
- **Voormalige huurders blijven nog even zichtbaar** - zodra een kamer een
  andere naam krijgt (via een nieuw huurcontract, of handmatig bij Huurders
  bewerken) wordt de vertrekkende huurder automatisch gearchiveerd in een
  apart "Vertrokken"-tabblad (naam, contactgegevens, contract-einddatum,
  vertrekmoment). Op de Huurders-pagina verschijnt daaronder een grijze
  sectie "Voormalige huurders (recent vertrokken)" met hun gegevens (mailen/
  bellen blijft mogelijk), tot **1 maand na hun contract-einddatum** - daarna
  verdwijnt die regel vanzelf uit dat overzicht (de sheetregel zelf blijft
  gewoon staan, wordt alleen niet meer getoond). Werkt onafhankelijk van of
  er intussen alweer een nieuwe huurder in diezelfde kamer zit.
- **Contracten** - vult een sjabloon in met de pand- en huurdersgegevens tot een
  concept-huurcontract, inclusief echte **PDF-download** (handig om direct te
  uploaden naar DocHub voor de handtekeningaanvraag). **Let op:** dit is een
  voorbeeldsjabloon, geen juridisch gecontroleerd contract - zie "Huurcontracten
  genereren" hieronder.
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
  en upload je foto's/video's. Zodra je opslaat, verschijnt de kamer op
  `steenhub.nl/aanbod` en op zijn eigen deelbare pagina
  `steenhub.nl/aanbod/<pand-slug>/<kamernaam>` - geen login nodig om die te
  bekijken.
- **Reageren**: bezoekers klikken op "Apply for this room" en vullen een
  formulier in (naam, contactgegevens, studie, studentnummer, gewenste
  ingangsdatum/huurduur, inkomsten, borgsteller ja/nee, voorkeur voor een
  fysieke bezichtiging of videobellen, en een verplichte upload van hun bewijs
  van inschrijving). Bewust een aantal extra vragen, zodat vooral serieus
  geïnteresseerden de moeite nemen te reageren. Het bewijs van inschrijving
  wordt lokaal op de server opgeslagen (zie "Lokale opslag van foto's/video's/
  bewijsstukken" hieronder) en is alleen te bekijken via een besloten link
  voor ingelogde beheerders van dat pand - dus nergens publiek te downloaden.
- **Aanmeldingen bekijken**: ga naar **"Aanmeldingen"** in de site-navigatie
  (alleen zichtbaar/toegankelijk voor ingelogde beheerders van dat pand) voor
  een overzicht van alle reacties, met een link naar het geuploade bewijs van
  inschrijving. Heb je een huurder gekozen? Klik op **"Lijst wissen"** om
  helemaal opnieuw te beginnen voor de volgende keer dat de kamer vrijkomt.
- Vanuit een aanmelding kun je wel direct op **"Contract maken"** klikken - dat
  opent "Nieuw huurcontract" met naam, studentnummer en kamer al ingevuld.

### Lokale opslag van foto's/video's/bewijsstukken

De foto's/video's van "Aanbod beheren" en de bewijsstukken van inschrijving bij
aanmeldingen staan **niet** op Google Drive, maar lokaal op de server, onder
`<STATE_DIR>/media/<pand>/<aanbod of aanmeldingen>/<kamer>/`. Reden: een Google
*service account* (het soort inlog dat deze site gebruikt) heeft zelf 0 GB
Drive-opslagruimte. Zodra de site een bestand probeert te **uploaden** naar een
gewone, persoonlijke Drive-map die alleen met dat account gedeeld is, weigert
Google dat altijd met een "storageQuotaExceeded"-fout - ongeacht bestandsgrootte.
Lokale opslag omzeilt dit probleem volledig. `STATE_DIR` is dezelfde blijvend
gekoppelde data-map die ook de betaalcontrole-cache gebruikt (`/app/data` op de
VPS), dus deze bestanden overleven gewoon een herbuild/redeploy.

**Let op:** de **Documenten**-pagina staat nog wel op Google Drive en heeft
dus in theorie dezelfde upload-beperking (browsen/downloaden werkt daar prima,
alleen nieuwe uploads zouden mislukken). Dat is bewust buiten scope gelaten
toen dit werd opgelost - laat het weten als je dat ook lokaal opgeslagen wilt
hebben.

## Huurcontracten genereren

Het contractsjabloon (`contract_templates/huurovereenkomst_voorbeeld.html`) is
gebaseerd op een echt (Engelstalig) tijdelijk huurcontract-op-kamerbasis en
bevat alle 16 standaardartikelen (gehuurde ruimte, duur, studentclausule, huur
en kosten, betaaltermijn, waarborgsom, servicekosten-afrekening,
gemeentelijke belastingen, huisregels, onderhoud, toepasselijk recht,
borgstelling, reparaties, toegang, verzekering, informatieplicht Wet goed
verhuurderschap) plus een handtekeningenblok. **Let op:** dit is een
voorbeeldsjabloon, geen juridisch gecontroleerd contract - laat een
jurist/Woonbond/de Rijksoverheid-modelovereenkomst meekijken voordat je dit
daadwerkelijk laat ondertekenen.

- **Pandgegevens invullen (eenmalig per pand)**: ga naar **Panden beheren >
  bewerken** en vul onderaan de contractvelden in: verhuurder(s) (naam +
  adres, één per regel), postcode/plaats, naam rekeninghouder, gedeelde
  ruimtes, bijzondere bepalingen/huisregels (vrije tekst, komt letterlijk in
  het contract) en het gemeentelijk meldpunt ongewenst verhuurgedrag. Zonder
  deze gegevens blijven er `[fill in]`-plekken in het gegenereerde contract
  staan.
- **Contract genereren**: ga naar **Contracten > Nieuw huurcontract**, kies een
  kamer (vult automatisch de gegevens in die al bekend zijn bij Huurders) en
  vul de rest aan (geboortedatum, studentnummer, borgsteller, huurprijs,
  waarborgsom, ingangs-/einddatum, etc.). Bij het opslaan worden deze gegevens
  ook teruggeschreven naar de Huurders-sheet (kolommen R t/m Y, inclusief de
  waarborgsom), zodat ze bij een volgend contract - of gewoon op de
  Huurders-pagina - meteen weer klaarstaan, én meteen meetellen bij de
  eerstvolgende "Betaalgeschiedenis aanvullen". Dit is een vinkje (standaard
  aan) onderaan het formulier - zet 'm uit voor een proefcontract dat je nog
  niet in de sheet wilt verwerken.
- **PDF-export**: elk gegenereerd contract heeft een **"Download als PDF"**-
  link (op de Contracten-pagina en bovenaan het contract zelf) - handig om
  direct te uploaden naar DocHub voor de handtekeningaanvraag. Er is ook nog
  een "Print / opslaan als PDF"-knop die de browser-eigen afdrukfunctie
  gebruikt, als alternatief.
- **Contract verwijderen**: elk contract op de Contracten-pagina heeft een
  "Verwijderen"-knop (met een bevestigingsvraag) - handig om een
  proefcontract of een verkeerd ingevuld exemplaar weer op te ruimen. Dit
  verwijdert alleen het gegenereerde contractbestand zelf, niet de
  huurdersgegevens in de sheet.
- **Concept-contract mailen**: na het genereren kom je direct op een
  mailscherm terecht (ook later nog te vinden via "Mailen naar huurder" bij
  elk contract op de Contracten-pagina) - met het e-mailadres van de huurder
  al ingevuld (uit het "E-mailadres huurder"-veld van het formulier) en een
  kant-en-klare Engelstalige tekst: het concept ter beoordeling, met vragen
  welkom, en uitleg dat er na akkoord een betaalverzoek en een link om
  elektronisch te tekenen volgt (zie hieronder), gevolgd tot slot door de
  digitale Bold-sleutel (actief vanaf de ingangsdatum). Onderwerp en tekst
  zijn nog aan te passen voordat je 'm verstuurt. De PDF van het contract
  gaat automatisch als bijlage mee, verzonden vanaf info@steenhub.nl, met de
  beheerders (EMAIL_BCC + het pand-specifieke `extra_bcc`) blind (BCC)
  meegenomen - de huurder ziet deze adressen niet.
- **Elektronisch ondertekenen** (in plaats van DocHub): op de Contracten-
  pagina staat bij elk concept-contract een link **"Verzoek tot tekenen"**,
  die eerst een **voorbeeldscherm** toont (net als bij "Mailen naar
  huurder") - onderwerp/tekst van de mail aan de huurder zijn nog aan te
  passen, en er staat een vinkje **"Gegevens ook terugschrijven naar de
  Huurders-sheet"** (standaard aan, zoals bij het genereren van het
  contract) voor als dat nog niet gebeurd was. Pas na bevestigen wordt er
  echt gemaild:
  1. de huurder krijgt de (evt. aangepaste) mail met een **betaalverzoek**:
     waarborgsom + de pro-rata huur vanaf de ingangsdatum t/m het einde van
     die kalendermaand, met het sommetje er duidelijk bij uitgeschreven
     (bv. "Security deposit: EUR 1.000,00" / "Pro-rated rent from
     10-07-2026 to 31-07-2026 (22 days): EUR 660,00") in plaats van alleen
     het opgetelde eindbedrag, plus een link om het contract op de site
     zelf te tekenen;
  2. alle verhuurder(s) van het pand (dezelfde adressen als EMAIL_BCC + het
     pand-specifieke `extra_bcc`) en, als er een borgsteller met e-mailadres
     is opgegeven, ook de borgsteller krijgen elk een eigen (niet aan te
     passen) mail met alleen hun tekenlink;
  3. elke link toont het volledige contract plus een ondertekenformulier:
     volledige naam, een **met de vinger/muis/stylus getekende handtekening**
     (canvas, verplicht) en een akkoordvakje - bij het tekenen wordt de
     handtekening, tijdstip, IP-adres en de getypte naam vastgelegd als
     audit-trail (een "gewone" elektronische handtekening, SES onder de
     eIDAS-verordening - voor een tijdelijk kamerhuurcontract in Nederland
     rechtsgeldig);
  4. zodra **iedereen** getekend heeft, wordt automatisch de definitieve
     versie gemaakt (bestandsnaam eindigt op `-getekend`, met een groene
     "Getekend"-badge op de Contracten-pagina, ter onderscheid van het
     "Concept", en met de getekende handtekeningen zichtbaar in het
     handtekeningenblok) en als PDF gemaild aan alle partijen, met de
     vermelding dat dit document nodig is om bij de gemeente in te
     schrijven op het adres.

  De voortgang ("Ondertekenstatus") is op elk moment te bekijken via de link
  naast een concept-contract (verschijnt pas ná het versturen) - daar kan
  ook per persoon opnieuw gemaild worden, mocht een link kwijtgeraakt zijn.
- **Contractsjabloon aanpassen** (alleen voor beheerders met toegang tot alle
  panden): via **Contracten > Contractsjabloon aanpassen** pas je de
  artikelen van het huurcontract zelf aan, in een simpel tekstverwerker-
  scherm (typen + koppen/vet/cursief/lijst via knoppen, geen HTML-code te
  zien) - de vaste opmaak eromheen (CSS, kop met partijengegevens,
  handtekeningenblok) staat hier niet bij en blijft ongewijzigd. Geldt voor
  **alle** panden. Tussen de tekst staan nog wel stukjes zoals
  `{{ huurprijs }}` en `{% if ... %}` - dat zijn de plekken waar automatisch
  gegevens worden ingevuld of een stuk tekst automatisch aan/uit gaat (bv.
  alleen tonen als er een borgsteller is); laat die intact. De pagina
  valideert de Jinja2-syntax vóór het opslaan (een kapotte `{% if %}` wordt
  geweigerd, de vorige versie blijft dan gewoon actief), en er staat een
  "Terugzetten naar standaardtekst"-knop voor als je toch iets wilt
  herstellen. De aanpassing wordt in `STATE_DIR` opgeslagen, overleeft dus
  een herbuild/redeploy. Test een wijziging altijd eerst met een
  proefcontract voordat je 'm naar een echte huurder stuurt.
- **Gegenereerde contracten overleven een redeploy**: net als de
  contractsjabloon-aanpassing staan gegenereerde contracten (HTML + de
  metadata voor het mailscherm) onder `STATE_DIR` (dus `/app/data` op de
  VPS, gekoppeld aan een volume in docker-compose.yml), niet los in de
  containercode - ze gaan dus niet verloren zodra `docker compose up -d
  --build` een nieuwe container opbouwt.
- De WWS-puntentelling (Annex 1, verplicht volgens de Wet goed
  verhuurderschap) wordt niet automatisch gegenereerd - reken deze zelf uit
  en voeg 'm apart toe als bijlage.

## Verwachte kolomindeling in de Google Sheet (per pand)

Elk pand heeft zijn eigen tabblad/sheet, aangesloten op je bestaande
huuradministratie. Rij 1 = koppen, data vanaf rij 2, één rij per kamer:

| A Kamer | B Huurder | C Kale huurprijs | D Servicekosten | E Totale huur | F Contract einddatum | G Opmerking | H IBAN | I Zoekwoord | J Status | K Ontvangen bedrag | L Laatst gecontroleerd | M Beschikbaar | N Advertentie omschrijving | O Advertentie map-ID | P Mail | Q Telefoonnummer | R Geboortedatum | S Geboorteplaats | T Studentnummer | U Studierichting | V Borgsteller naam | W Borgsteller relatie | X Contract startdatum | Y Borg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BG straatkant | Henri Maarten Slendebroek | 700,94 | 44,06 | 745,00 | 31-07-2026 | gaat er per 31-07-2026 uit | | | | | | | | | | | | | | | | | | |

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
- Kolom **P en Q** (Mail, Telefoonnummer) zijn nieuw en optioneel -
  contactgegevens van de huurder, te bewerken via de Huurders-pagina op de
  site en zichtbaar op de kamerpagina (met directe mailto:/tel:-links).
- Kolom **R t/m X** (Geboortedatum, Geboorteplaats, Studentnummer,
  Studierichting, Borgsteller naam, Borgsteller relatie, Contract
  startdatum) zijn nieuw en optioneel - bedoeld om een huurcontract mee voor
  te vullen (zie "Huurcontracten genereren" hieronder) én, specifiek kolom
  **X (Contract startdatum)**, om te bepalen vanaf welke maand
  "Betaalgeschiedenis aanvullen" voor die kamer terugzoekt (zie hierboven).
  Formaat dd-mm-jjjj. Te bewerken via de Huurders-pagina; worden ook
  automatisch bijgewerkt zodra je voor die kamer een contract genereert.
- Kolom **Y (Borg)** is nieuw en optioneel - de waarborgsom die de huurder in
  de instapmaand betaalt (naast de eerste huur). Wordt gebruikt bij
  "Betaalgeschiedenis aanvullen" en de actuele controle om te voorkomen dat
  de instapmaand als "Te veel ontvangen" verschijnt (zie hierboven).
- **Totale huur** (kolom E) is het bedrag dat de site verwacht via bunq binnen
  te zien komen (kale huur + servicekosten).
- Een lege **Huurder** met een ingevulde **Kamer** betekent: kamer staat leeg.
- Een **somrij** onderaan (Kamer-kolom = "Totalen" of "Totaal") wordt door de
  site automatisch genegeerd - die mag gewoon blijven staan.
- **Contract einddatum** (kolom F, formaat `dd-mm-jjjj`) wordt ook gebruikt
  voor de aanzeg-waarschuwing op het dashboard. Leeg laten (of "onbepaalde
  tijd" erin zetten) als het contract geen einddatum heeft.

Er wordt automatisch een tweede tabblad (**Historie**, naam instelbaar per
pand) aangemaakt met kolommen **Maand | Kamer | Huurder | Verwacht bedrag |
Ontvangen bedrag | Status | Betaaldatum**. Per kamer komt er precies **1 regel
per kalendermaand** in - een "Nu controleren"-run werkt de regel van de
huidige maand bij in plaats van er een nieuwe aan toe te voegen, zodat vaker
controleren binnen dezelfde maand de betrouwbaarheidsscore niet vertekent.
"Betaaldatum" is de datum van de (laatste) gematchte betaling, dus een late
betaling blijft zichtbaar als "laat betaald" ook al staat de status
inmiddels gewoon op "Betaald". Dat voedt de betaalgeschiedenis en
betrouwbaarheidsscore op de kamerpagina's.

> Was je Historie-tabblad al aangemaakt vóórdat deze indeling bestond (oude
> koprij: Datum | Kamer | Huurder | Verwacht bedrag | Ontvangen bedrag |
> Status)? De site laat die oude regels dan gewoon met rust (ze crashen niets,
> maar worden ook niet meer getoond) en telt vanaf nu opnieuw per maand mee.

De kolom "Maand" wordt weggeschreven als platte tekst (`value_input_option=RAW`),
niet als datum - Google Sheets herkende een waarde als "2026-06" anders soms zelf
als datum en zette 'm om naar "01-06-2026", waardoor de site zijn eigen regels
niet meer terugvond en er dubbele regels bijkwamen. Regels die al zo omgezet
waren (van vóór deze fix) worden bij het lezen/opschonen gewoon herkend en
teruggezet naar het normale "jjjj-mm"-formaat.
> Wil je een nette overgang, werk dan zelf de koprij bij naar **Maand | Kamer
> | Huurder | Verwacht bedrag | Ontvangen bedrag | Status | Betaaldatum** (voeg
> kolom G toe) - nieuwe tabbladen krijgen deze koprij automatisch.

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

## Stap 2b: e-mail versturen instellen (optioneel, voor de herinnering/ingebrekestelling-knoppen)

Alleen nodig als je de knoppen "Stuur herinnering"/"Stuur ingebrekestelling" op
de Betalingen-pagina wilt gebruiken. Je hebt een mailbox nodig die e-mail mag
versturen via SMTP - bijvoorbeeld `info@steenhub.nl` als die mailbox al bij je
hostingpartij/domeinregistrar hoort, of anders een Gmail-account met een
[app-wachtwoord](https://myaccount.google.com/apppasswords) als tijdelijke
oplossing.

Zet in `.env` (op de VPS in `deploy/app.env`, zie Stap 7):

```
SMTP_HOST=smtp.jouwprovider.nl
SMTP_PORT=587
SMTP_USERNAME=info@steenhub.nl
SMTP_PASSWORD=jouw-wachtwoord-of-app-wachtwoord
SMTP_FROM_EMAIL=info@steenhub.nl
SMTP_FROM_NAAM=Steenhub
EMAIL_BCC=jouw-eigen-email@voorbeeld.nl
```

`EMAIL_BCC` is een komma-gescheiden lijst en geldt voor **alle** panden - zet
hier dus alleen adressen in die overal mogen meelezen (bv. je eigen adres).
Zonder deze instellingen blijven de knoppen gewoon zichtbaar, maar krijg je
bij het versturen een nette foutmelding in plaats van een crash.

Wil je dat een mede-eigenaar alleen bij één specifiek pand wordt meegekopieerd
(bv. Justin, die alleen mede-eigenaar is van Mahoniestraat en niet van je
andere panden)? Vul dat adres dan in bij "Extra BCC" op de bewerkpagina van
dát pand (Panden > Bewerken) in plaats van in `EMAIL_BCC` - die adressen gaan
alléén mee bij mails van dat ene pand, naast de adressen uit `EMAIL_BCC`.

> De ingebrekestelling-tekst is een standaardformulering (redelijke termijn
> om alsnog te betalen, art. 6:82 BW) - geen juridisch advies. Je kunt de
> tekst altijd aanpassen op het voorbeeldscherm voordat je 'm verstuurt, en
> laat 'm bij een echt geschil het beste even meelezen door een jurist/
> rechtsbijstandsverzekeraar.

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
- Dit `properties.json`-bestand is alleen nodig om het **allereerste** pand in
  te stellen (er moet minstens één pand zijn voordat de site opstart). Nieuwe
  panden voeg je daarna toe via de site zelf, zie hieronder - geen
  command line of herstart meer nodig.

### Nieuw pand toevoegen via de site ("Panden beheren")

Beheerders met toegang tot alle panden zien een **"Panden"**-knop in de
navigatie. Daar kun je een nieuw pand toevoegen (naam, Google Sheet ID,
tabbladnamen, optioneel een Drive-map-ID, en het bunq-IBAN), bewerken, of
verwijderen. Wijzigingen gelden meteen, geen herstart nodig - net als bij
Gebruikers. Onderaan het bewerkformulier staan ook de contractgegevens van dat
pand (verhuurder(s), postcode/plaats, naam rekeninghouder, gedeelde ruimtes,
bijzondere bepalingen, gemeentelijk meldpunt) - zie "Huurcontracten
genereren" hierboven.

Dat scheelt SSH/JSON-bewerken, maar de "echte wereld"-voorbereiding blijft
hetzelfde als bij het eerste pand:

1. Maak (of hergebruik) een Google Sheet met de juiste kolomkoppen (zie
   hierboven) voor het nieuwe pand, en deel 'm met het `client_email`-adres
   uit je `google-service-account.json` (Stap 2) - hetzelfde service-account
   werkt voor alle panden, je hoeft niks opnieuw aan te maken in Google Cloud.
2. Optioneel: maak een Drive-map voor documenten/aanbod-foto's van dat pand,
   en deel die ook met hetzelfde `client_email`-adres.
3. bunq: als de rekening van het nieuwe pand **onder dezelfde bunq-login**
   valt als je bestaande panden (meestal het geval - één bunq-profiel met
   meerdere rekeningen), is er **geen nieuwe API key** nodig. Zoek gewoon het
   IBAN van de juiste rekening op in de bunq-app en vul dat in. Alleen als het
   een compleet aparte bunq-zakelijke login/profiel is, is een nieuwe
   `setup_bunq.py`-koppeling nodig.
4. Vul daarna het formulier op "Panden > Nieuw pand" in met de slug, naam,
   sheet ID, en IBAN.

Toegang geven aan gebruikers (bijv. alleen jijzelf, niet Justin, voor een
pand dat volledig van jou is) regel je zoals gewoonlijk via "Gebruikers".

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
  handig als bijvoorbeeld een ouder betaalt. Een IBAN of zoekwoord is
  betrouwbaarder, maar is **geen exclusieve eis**: matcht het IBAN op de
  sheet niet met de daadwerkelijke afzender (bijv. een typefout, of iemand
  anders betaalt namens de huurder), dan valt de site automatisch terug op
  naam-matching in plaats van niets te vinden.
- **Welke maand telt een betaling mee, bij vroeg/laat betalen?** Een vaste
  regel: komt een betaling binnen op de **1e t/m de 17e** van de maand, dan
  telt hij voor díe maand. Komt hij binnen vanaf de **18e t/m het einde** van
  de maand, dan telt hij voor de **maand erna** (bv. een huurder die al op de
  20e vooruitbetaalt voor volgende maand). Dit geldt zowel voor de
  actuele controle als voor "Betaalgeschiedenis aanvullen", zodat een
  huurder die structureel vroeg of laat betaalt niet om en om als "te veel"/
  "niet ontvangen" verschijnt.
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
