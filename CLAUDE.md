# CLAUDE.md — projectgeheugen Steenhub

> Dit bestand wordt elke sessie automatisch ingeladen. Het is het blijvende
> geheugen voor deze repo en de Steenhub-apps. **Houd het actueel en opgeschoond:**
> werk het bij zodra er iets structureels verandert (nieuwe app, branch, regel,
> architectuurkeuze), en haal verouderde dingen weg. Houd het feitelijk en bondig.
>
> **Bewust NIET in dit bestand** (want het wordt gecommit naar GitHub + uitgerold
> naar de VPS): persoonlijke/financiële gegevens en data van derden — concrete
> WOZ-waarden van kandidaat-panden, leningen (vader, Niels), namen van mede-eigenaren
> of huurders, koopovereenkomsten, onderhandelingsstrategie. Die horen in de lopende
> chat of een privé-document, niet in de repo. Hieronder staan alleen technische
> projectkennis en algemene (openbare) domeinregels.

---

## 1. Wat is dit

Eén monorepo (`jmmreckman/kamerverhuur-scanner`) met **meerdere los uitgerolde
apps**, elk op een eigen branch die naar een eigen subdomein deployt. De repo bevat
de volledige boomstructuur op elke deploy-branch; per subdomein wordt een andere
app-map/branch gedraaid.

Eigenaar/hoofdgebruiker: Jurian Reckman (`jmmreckman@gmail.com`), kamerverhuur-
belegger in Rotterdam. Mede-gebruiker van de steenhub-app: Justin (beperkte
pandtoegang). Waarde die de gebruiker expliciet vraagt: **eerlijk, gekalibreerd,
niet-sycofantisch** advies — liever een onderbouwde tegenwerping dan meegaan.

---

## 2. Apps / subdomeinen → map → branch

| Subdomein | Map | Branch | Wat het is |
|---|---|---|---|
| **steenhub.nl** (hoofd-app) | `webapp/` | `claude/student-housing-rent-tracker-u2fb2f` | Huurdersadministratie: betalingen-check (bunq), huurcontracten, documenten, tekenportaal, aanbod/aanmeldingen, bezichtigingen, winstberekening, pandkiezer. |
| **kansen.steenhub.nl** | `kansen_site/` | `claude/rotterdam-property-scraper-impfg0` | Funda/woning-scanner + interactieve **rekentool** per woning (investeringsberekening, rente/ICR, "aan te tonen eigen middelen"), rentegrafiek, mailvoorkeuren. |
| **gewicht.steenhub.nl** | ? | vermoedelijk `claude/weight-tracking-portal-x3phgn` | Gewicht-tracking. **Details onbekend — zit in een andere chat; aanvullen.** |
| **opdracht.steenhub.nl** | ? | vermoedelijk `claude/teacher-communication-system-7kWkk` of `claude/student-worksheet-portal-o9IYt` | Onbekend (opdrachten/onderwijs?). **Aanvullen vanuit die chat.** |
| **rommel.steenhub.nl** | ? | ? | Onbekend — zit in een andere chat. **Aanvullen.** |

Andere remote branches gezien: `claude/funda-scraper-script-ovafC` (vroege
funda-scraper, waarschijnlijk voorloper van kansen). `main` = basis.

> De gewicht/opdracht/rommel-mapping hierboven is een **vermoeden op basis van
> branchnamen**, niet bevestigd. Bevestig per subdomein welke branch/map erbij hoort
> en werk de tabel bij.

**Deze CLAUDE.md staat idealiter op beide actieve deploy-branches** (student-housing
én rotterdam-property-scraper), zodat hij laadt ongeacht welke app in bewerking is.

---

## 3. Deploy & build

- Push naar een deploy-branch → **GitHub Actions** (`.github/workflows/deploy.yml`)
  SSH't naar de VPS en rolt via `docker compose` uit naar het bijbehorende subdomein.
- De Dockerfile installeert `requirements.txt`. Nieuwe runtime-dependency → in
  `requirements.txt` zetten.
- Secrets staan als VPS-env (`fundazoeker.env` / `app.env`) en als **GitHub Actions
  secrets** (`DEPLOY_SSH_KEY` / `DEPLOY_HOST` / `DEPLOY_USER`), **nooit in git**.

### Hosting / server (feiten)
- **Provider: STRATO** — pakket **"STRATO VPS Linux S (a12.nl)"**, contract **10011227**.
  Draait fysiek op IONOS-infra (zelfde moederbedrijf; een IP-whois toont daarom
  "IONOS SE", niet Strato — geen tegenstrijdigheid).
- **SSH:** `ssh root@85.215.78.192` (Ubuntu 24.04). Dit IP is ook gewoon het publieke
  A-record van steenhub.nl, dus geen geheim; de **sleutel/wachtwoorden horen NIET in
  git** (zie boven).
- **Specs: 2 vCPU, 2 GB RAM, 90 GB schijf — klein.** Steady-state draait er ~1,2 GB
  RAM aan containers (webapp, gewicht, kansen, 3 scanners, caddy). Krap maar werkt.
- **Swap:** er staat sinds okt 2026 een **4 GB swapfile** (`/swapfile`,
  `vm.swappiness=10`) als vangnet tegen OOM tijdens builds. Blijft staan via
  `/etc/fstab`.
- **Beheer/reboot:** via **strato.nl → Login (Kundenlogin) → pakket "STRATO VPS
  Linux S" → Overzicht → Serverdetails**. Knoppen: *Opnieuw opstarten*, *Stoppen*,
  *VNC-console*, *Reddingssysteem*. **NOOIT "Opnieuw installeren"** — dat wist de
  hele server.

### Build-regels — NIET te snel/te zwaar bouwen (les okt 2026)
> Op deze 2 GB-box kan een te zware of parallelle build het geheugen opvreten →
> hele VPS onbereikbaar (óók SSH), site geeft "connection timed out", terwijl
> Strato nog "Draait" toont (OS hangt door OOM).
- **Niet meerdere deploys kort achter elkaar pushen.** Elke push = een build op de
  VPS; overlappende builds stapelen op. Push **één branch tegelijk en wacht tot de
  Actions-run groen is** voor de volgende.
- **Geen `--no-cache`** en **niet álle services tegelijk** herbouwen. Per push alleen
  de services van de app die je uitrolt, mét laag-cache:
  - **steenhub-deploy:** git pull op VPS, dan `docker compose build app
    dagelijkse-check winst-snapshot` + `up -d` van diezelfde drie (ze delen één image).
  - **kansen-deploy:** bouwt `fundazoeker kansen beschikbaarheid-check
    vergunningen-index` vanaf een remote git-context (kortlevende `GITHUB_TOKEN` via
    tijdelijke `docker-compose.override.yml`), mét cache.
- **Herstel bij een platte VPS:** SSH én site timen out = OS hangt (meestal OOM).
  Fix = **harde reboot via het Strato-paneel** (buiten SSH om). Containers staan op
  `restart: unless-stopped`, dus ze komen vanzelf terug op de laatst-gebouwde images
  (de vorige werkende versie). Een mislukte/halve deploy raakt de draaiende containers
  niet — die blijven de oude, werkende images draaien tot een build+`up -d` slaagt.
- **Toekomst-optie (bij vaak deployen):** images in GitHub Actions bouwen en de VPS
  alleen `docker compose pull` + `up -d` laten doen → de VPS compileert dan nooit meer
  iets. RAM naar 4 GB is comfort, geen noodzaak.

---

## 4. Waar zit wat (per app)

### steenhub.nl (`webapp/`, package `kamerverhuur_scanner/`)
- `webapp/app.py` — Flask-routes (dashboard, betalingen, contracten, documenten,
  tekenportaal, pandkiezer, panden-beheer, gebruikers).
- `kamerverhuur_scanner/sheet_client.py` — Google Sheets lezen/schrijven
  (`gspread`, service account). Kolomindeling Huurders A–AD staat hier
  (`HUURDERS_HEADER` + `COL_*`). **`bouw_sheet_structuur()` / `SheetClient.bouw_structuur()`**
  bouwt bij een nieuw pand automatisch alle tabbladen + koprijen (Huurders, Historie,
  Aanmeldingen, Bezichtigingen, Vertrokken). `sheet_id_uit_invoer()` haalt het ID uit
  een geplakte link.
- `kamerverhuur_scanner/runner.py` — `run_check()` (betaalcontrole),
  `bereken_winstoverzicht()`, `backfill_geschiedenis()`.
- `kamerverhuur_scanner/bunq_client.py` — bunq-API (betalingen ophalen).
- `kamerverhuur_scanner/drive_sync.py` + `drive_browse.py` — Drive via **rclone**.
- `webapp/tekenportaal.py` + `handtekening.py` + `ondertekenen.py` + `contracts.py`
  — document/contract tekenen (pymupdf stempelt, xhtml2pdf voor contracten).
- `kamerverhuur_scanner/models.py` — dataclasses (`Pand`, `Tenant`, …).
- `kamerverhuur_scanner/utils.py` — o.a. `is_bunq_iban()`.
- `kamerverhuur_scanner/state.py` — kleine JSON-state in `state_dir` (laatste
  resultaat, verzonden mails, winst-geschiedenis, **pand-volgorde per gebruiker**).

### kansen.steenhub.nl (`kansen_site/`, package `rotterdam_scanner/`)
- `rotterdam_scanner/investering.py` — **rekentool-model** (`bereken_rekentool`,
  `RekenUitgangspunten`, `RekenResultaat`): taxatie voor/na, leenbaar, verhoogbaar,
  "aan te tonen eigen middelen", **ICR vóór/ná ophoging** (norm 1,25).
- `rotterdam_scanner/domivest_rente.py` + `rente_update.py` — scrapet de
  Domivest-verhuurhypotheekrente; houdt een **eigen bron-van-waarheid**
  (`domivest_rente_state.json`) los van het door de gebruiker bewerkbare renteveld;
  mailt alleen bij een échte wijziging op de Domivest-site. Rentegrafiek-historie
  in `rente_historie.json`.
- `kansen_site/app.py`, `kansen_site/templates/berekening.html`,
  `kansen_site/static/berekening.js/.css`, `kansen_site/rapport_pdf.py` (PDF-export).
- `rotterdam_scanner/mailer.py` — uitgaande mail; **stille BCC** naar
  `jmmreckman@gmail.com` (in SMTP-envelope, niet in headers). `send_mail(...,
  stille_bcc=False)` laat die BCC weg — gebruikt door de concurrentie-scan, waar de
  gebruiker zelf de ontvanger(s) kiest.
- `rotterdam_scanner/opkoop_scan.py` — **concurrentie-scan** op de kaart (beheerder):
  trechter binnen 50 m rond een adres → 1) alle adressen (PDOK reverse, gepagineerd,
  rows max 100) 2) opkoopbescherming (WOZ per adres, alleen in een beschermde wijk)
  3) 50 m-norm (`gis.binnen_50m_van_kamerverhuurvergunning`) 4) vermelding (géén harde
  uitsluiting): BAG-oppervlakte <72 m² + te-koop-geweest (uit het archief). Mailt het
  resultaat naar een zelf op te geven ontvanger-veld (komma = meerdere; leeg = het
  mailadres uit de mail-voorkeuren van het ingelogde account). Ook te starten vanuit
  het kaart-popup per woning. Route `POST /opkoop-scan`. **Beperking:** lopende/
  onverwerkte kamerverhuur-*aanvragen* zijn niet te zien — Rotterdam publiceert alleen
  de beslissing, niet de aanvraag.
- **Favorieten zijn per account** (`ListingState.favoriet_accounts`, niet meer de oude
  gedeelde `favoriet`-bool — die telt alleen nog als legacy "voor iedereen" tot 'ie
  opnieuw getoggled wordt). Een woning favoriet maken start op de achtergrond (zonder
  mail) een concurrentie-scan; de 1-zins-samenvatting (`concurrentie_samenvatting`,
  woning-niveau) verschijnt in het kaart-popup.
- `rotterdam_scanner/archief.py` — **blijvend listings-archief**
  (`listings_archief.json`, naast `state.json`). **Bewaart ÁLLE ooit geziene listings
  voor altijd en wordt elke scan-run aangevuld — NOOIT prunen/leegmaken.** `StateStore`
  ruimt listings na ~30 dagen op (schone kaart); dit archief juist niet, zodat je
  woningen altijd kunt terugzoeken (bv. "stond dit adres ooit te koop?", of in de
  toekomst terugkerende woningen). Gevuld in `pipeline._vul_archief_aan` vóór
  `prune_expired`; gelezen door de concurrentie-scan. Geen terugwerkende kracht
  (woningen die vóór de invoering al geprund waren, zijn weg).

---

## 5. Google / bunq / Drive-architectuur (belangrijk)

- **Google Sheets** = via **service account** (`gspread`), per sheet-ID. Elke sheet
  moet gedeeld zijn met het service-account-adres (`client_email` uit
  `google-service-account.json`). `service_account_email()` toont dat adres.
- **Drive (documenten/contracten)** = via **rclone** op de eigen Google-login van de
  gebruiker (2 TB). Mappen: `Steenhub <pandnaam>/` (Huidige/Oude huurders), plus
  `Steenhub getekende documenten`.
- **Waarom die splitsing:** het service account heeft **0 GB eigen Drive-opslag**
  (`storageQuotaExceeded`), dus het kan zelf geen bestanden/sheets bezitten. Daarom
  is "nieuw pand → sheet aanmaken" **half-automatisch**: gebruiker maakt zelf een
  lege sheet + deelt 'm met het service account; de app bouwt dan de tabbladen/kopjes.
- **bunq:** betalingen worden alleen uitgelezen voor panden met een **bunq-IBAN**
  (`Pand.heeft_bunq_rekening` / `is_bunq_iban()`, bankcode `BUNQ`). Panden met een
  andere bank (bv. een Rabo-rekening) slaan de automatische betaalcontrole/lastenscan
  netjes over (geen fout); betalingen handmatig bijhouden.

---

## 6. Testomgeving-beperkingen (sandbox)

In de Claude-sandbox bouwen/installeren sommige dependencies niet:
- **`bunq_sdk`** (wheel bouwt niet) en **`xhtml2pdf`** (conflict met systeem-
  `cryptography`). Daardoor zijn de tests die `webapp.app` importeren hier **niet te
  draaien** — die draaien wel in CI/productie.
- `gspread`, `flask`, `flask_login`, `anthropic`, `pymupdf` zijn soms wél los te
  pip-installen om deeltests te draaien.
- Praktijk: logica zo schrijven dat de **pure delen los testbaar** zijn (fakes),
  bv. `bouw_sheet_structuur` werkt op een gspread-achtig object; `is_bunq_iban`,
  `sorteer_op_volgorde`, rekentool-functies hebben geen externe deps.

---

## 7. Conventies / afspraken

- **Branch-gebruik:** ontwikkel elke app op zijn eigen deploy-branch (zie §2).
  Niet pushen naar andere branches zonder expliciete toestemming. Geen PR's tenzij
  gevraagd.
- **Secrets:** alleen als VPS-env, nooit committen of in chat plakken.
- **Commit-attributie** (chat-afspraak): eindig commits met
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` en
  `Claude-Session: <sessielink>`. **Nooit** een model-identifier in commits/PR's/code.
- **GitHub** via de MCP-tools (`mcp__github__*`) of `gh api`.
- Taal richting gebruiker: Nederlands.

---

## 8. Domeinkennis — WWSO (woningwaardering onzelfstandige woonruimte, per 1-7-2024)

Voor kamerverhuur. **Gedeelde voorzieningen worden gedeeld door het aantal kamers met
toegang** → delen-en-weer-optellen verandert het huis­totaal niet (alleen de
verdeling). Totaal verhoog je door méér/betere voorzieningen, niet door anders te delen.

- **Buitenruimte:** privé = **2 + 0,35/m²** (max 15, geen min. maat); gedeeld =
  **0,75/m² ÷ aantal kamers** (huis­totaal = 0,75 × m²). Max 15 punten (privé+gedeeld
  samen) per kamer. → Een gedeelde tuin levert voor realistische maten (≥~5 m²) meer
  op dan privé-aan-1 (hogere /m² + geen cap-verlies).
- **Overige ruimten / bergruimte / fietsenstalling:** **0,75/m²** (÷ kamers indien
  gedeeld). Aparte categorie van buitenruimte → m² onder een schuur telt niet meer als
  tuin, maar wel als berging (per saldo gelijk bij 0,75 vs 0,75 gedeelde tuin).
- **Gedeelde vertrekken** (keuken/woonkamer/gang): **1/m² ÷ kamers**.
- **Sanitair** (gedeeld ÷ aantal kamers): douche **3**, bad **5**, bad/douche **6**;
  wastafel **1** (brede/2-persoons ≥70 cm **1,5**); toilet apart **3** / in badkamer
  **2** / hangtoilet apart **3,75** / hangtoilet badkamer **2,75**.
- **Monument/gezicht:** **rijksmonument = +10 punten/kamer** (contracten ≥1-7-2024);
  **beschermd stads-/dorpsgezicht = +5% opslag op de max huur** (bouwjaar <1965, geen
  andere monumentopslag). **Niet combineerbaar.** Let op: een rijksmonument beperkt
  verbouwing/isolatie sterk → vaak net-negatief voor een strip-naar-kamers-plan.
- **Puntprijs:** ~€6/punt/maand (indicatief; jaarlijks indexeren — verifiëren).
- **Te verifiëren:** exacte /m²-waarde van de eigen (privé) kamer-oppervlakte.

Bron: Huurcommissie beleidsboek WWSO; Stb. 2024/194.

---

## 9. Domeinkennis — Rotterdam opkoopbescherming & kamerverhuurvergunning

**Opkoopbescherming (zelfbewoningsplicht):** geldt in 16 wijken voor woningen met
**WOZ t/m €470.000** (getoetst op de WOZ geldig op de passeerdatum). 4 jaar
zelfbewoningsplicht; verhuur alleen met vergunning; boete tot €21.750. 16 wijken:
Bergpolder, Blijdorp, Bloemhof, Carnisse, Groot-IJsselmonde, Hillegersberg-Zuid,
Hillesluis, Kralingen-Oost, Kralingen-West, **Het Lage Land**, Middelland, Nieuwe
Westen, **Oud-Charlois**, Oud-Mathenesse, Rubroek, Tarwewijk.
Bron: rotterdam.nl/opkoopbescherming.

**Kamerverhuur / omzettingsvergunning** (Verordening samenstelling woningvoorraad
2025, art. 2.2.x):
- **Vergunningplicht vanaf 3 bewoners.** 3 bewoners = licht regime (telt niet mee voor
  de 50 m-norm, geen extra eisen).
- **4+ bewoners = volledige toets:** min. **18 m²/persoon**; niet in een
  **nulquotumgebied**; **50 m-norm** (afstand tot een andere 4+-kamerverhuurvergunning,
  gemeten **BAG-coördinaat tot coördinaat**; alléén 4+-vergunningen tellen, 3-persoons
  niet); **uitsluitend verhuur aan studenten** (art. 2.2.4).
- **Nulquotumgebieden** (géén vergunning): Bergpolder, Carnisse, Kralingen Oost/West,
  Oud Mathenesse, Struisenburg, Tarwewijk.
- Praktische dreigingsanalyse bij een 50 m-ring: alleen buren die (a) binnen 50 m
  liggen én (b) zelf buiten alle bestaande 4+-cirkels vallen én (c) te koop/te pakken
  zijn, kunnen je voor zijn. Snelheid van je eigen aanvraag is de grootste mitigatie.
- Officiële kamerverhuurkaart toont per stip de vergunning (3 of 4 personen,
  besluitdatum) met 50 m-cirkel.

**Voorkeursrecht (Wvg / Omgevingswet):** rust op een perceel als ingeschreven in
kadaster/WKPB; getoetst door de notaris. Staat **niet** op Domivest's uitsluitingslijst.
Rotterdam vestigt het vooral bij grote herontwikkeling (bv. Feyenoord City), niet in
rustige woonwijken.

---

## 10. Domeinkennis — Domivest acceptatiegids (verhuurhypotheek, gedistilleerd)

(Uit de gids okt 2020; PDF niet in repo — in Drive bewaren. Verifieer bij een recentere
versie.)
- **Niet-toegestane onderpanden** o.a.: pand met **bezwarend kettingbeding**; pand met
  **beperkende zakelijke rechten voor de hypotheekhouder**; woning waarvoor de gemeente
  een **sloop/handhaven-afweging** heeft gemaakt; beslag; hypotheek t.g.v. derden;
  vruchtgebruik/recht van gebruik-bewoning; recreatiewoning; woning op bedrijventerrein;
  vervuilde grond; coffeeshop/growshop e.d. **Een gemeentelijk voorkeursrecht staat NIET
  op de lijst.**
- Woonbestemming vereist; combinatiepand mag, residentieel ≥80% van de waarde
  (commerciële huur telt niet mee in ICR/DSCR).
- **Geen eigen bewoning**; geen verhuur aan familie 1e/2e lijn.
- **Kamerverhuur:** alle benodigde vergunningen aanwezig; taxateur toetst
  huidig/verwacht gebruik aan gemeentebeleid.
- **Taxatie** door Domivest-goedgekeurde taxateur, Domivest is opdrachtgever; initiële
  taxatie max 6 maanden oud.
- **Familielening ≥ €20k:** getekende leningsovereenkomst + ID's + herkomst-onderbouwing
  geldgever + **per bank overgemaakt** (geen cash). Max 3 schenkingen/leningen per
  aanvraag; schenking vrij van last/tegenprestatie. **Geen verplichte leningsvorm**
  (niet per se direct-opeisbaar/achtergesteld).
- **ICR = kale huur / rente** (bruto, géén kostenafslag — die 70%/opex hoort in een
  netto/DSCR-berekening, niet in de ICR). Normen (indicatief): DSCR-vloer ~1,05;
  ICR-comfort ~175%; DSCR-comfort ~125%.

---

## 11. Domeinkennis — fiscaal / financiering (algemene regels, geen persoonsdata)

- **6%-norm familielening** (art. 15 Successiewet / HR 2016): rente onder 6% — of
  renteloos-direct-opeisbaar — creëert een jaarlijkse rentevoordeel-schenking. Veilig:
  ≥6% met boetevrije vervroegde aflossing.
- **Box 3 verhuur:** rente is **niet aftrekbaar** (geen renteaftrek zoals box 1 eigen
  woning).
- Schenkvrijstellingen (indicatief, **jaarlijks indexeren/verifiëren**): ~€6.700
  ouder-kind per jaar; ~€32k eenmalig verhoogd (18–40 jaar).
- Wwft: herkomst eigen middelen aantoonbaar, via bank.

---

## 12. Rekentool-model (kansen) — kernformules

- `taxatie_voor = koopsom × taxatieverhouding_voor`
- `taxatie_na = (kale_huur_pm × 12) / BAR`
- `leenbaar = LTV × taxatie` (voor/na)
- `verhoogbaar_met = leenbaar_na − leenbaar_voor`
- **Aan te tonen eigen middelen** = `in te brengen bij passeren`
  (= koopsom + OVB + kosten koper − leenbaar_voor) + `6 mnd financieringslasten
  verbouwing` + `3 mnd leegstandsrente`. Verbouwkosten lopen via **bouwdepot** → tellen
  hier NIET mee (verlagen wel "opname liquiditeit na verbouwing").
- **ICR** (groen ≥1,25, rood eronder): vóór ophoging = (⅓ × kale huur) / rente op lening
  vóór verhoging; ná ophoging = volle kale huur / rente op lening ná verhoging.
- OVB en rente komen uit de losse invoervelden → wijzigingen werken automatisch door.

---

## 13. Documentenopslag (bestanden die de gebruiker uploadt)

**Aanbevolen huis: Google Drive** (de app gebruikt 'm al via rclone), niet de git-repo.
PDF's van koopovereenkomsten, taxaties, huurcommissie-docs, de Domivest-acceptatiegids,
meetrapporten, energielabels e.d. horen daar — gestructureerd per pand of in een map
`Steenhub documentatie`. Claude kan Drive lezen via de Google-Drive-MCP wanneer nodig.

In dit bestand houden we alleen een **index + gedistilleerde feiten** bij, niet de
bestanden zelf (repo blijft schoon, geen gevoelige data in git).

**Index (aanvullen):**
- Domivest-acceptatiegids (okt 2020) — regels gedistilleerd in §10. PDF: in Drive zetten.
- Huurcommissie WWSO-beleidsboek — regels in §8.
- (Per pand: koopovereenkomst, taxatie, energielabel, meetrapport, vragenlijst B — in de
  Drive-pandmap.)

---

## 14. Onderhoud van dit bestand

- Werk bij zodra iets structureels verandert; verwijder verouderde info.
- Houd persoonlijke/financiële/derden-data eruit (zie kop).
- Bevestig en vul de gewicht/opdracht/rommel-rijen in §2 aan.
- Normen/bedragen in §8–§11 jaarlijks verifiëren (puntprijs, WOZ-grens, vrijstellingen).
