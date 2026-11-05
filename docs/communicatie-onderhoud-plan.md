# Bouwplan — Huurderscommunicatie & Onderhoudsbeheer (steenhub.nl)

> Levend plandocument. We vinken fases af terwijl we bouwen. Laatst bijgewerkt: 2026-10-25.
> Dit document bevat **geen** wachtwoorden/sleutels/persoonsdata — alleen de opzet.

## Doel
Eén centrale plek om te zien **wat aandacht vraagt**, en huurderscommunicatie +
onderhoud deels te automatiseren met de Claude API. Minder tijd kwijt aan oude mails
terugspitten; concepten laten voorschrijven; alles per huurder terugvindbaar.

## Uitgangspunten
1. **Jij blijft aan het stuur.** Elk AI-concept gaat eerst naar een goedkeuringswachtrij; niets
   wordt automatisch verstuurd.
2. **Scheiden in data, verenigen in beeld.** Onderhoud = gestructureerde tickets; communicatie =
   berichtenlog. Op de huurderspagina zie je beide in één tijdlijn.
3. **Samenvatting = index, log = waarheid.** De AI-samenvatting per huurder is voor snel overzicht;
   voor "wat zei die precies" blijft de volledige berichtenlog het origineel.
4. **Hergebruik wat er is.** Panden uit `properties.json`, huurders uit Google Sheets, mail via de
   bestaande `mailer`, AI via de bestaande `anthropic`-koppeling. Niet dupliceren.
5. **Toegang per gebruiker.** Het centrale overzicht toont alleen panden waar de ingelogde gebruiker
   bij mag (Justin ziet minder dan Jurian).
6. **Gefaseerd + testbaar.** Pure logica (DB-laag, prompt-bouw, mail-parser) los testbaar houden
   (webapp.app is in de sandbox niet importeerbaar).
7. **Geen secrets in git.** Nieuwe inloggegevens alleen als VPS-env (`app.env`).

## Architectuurkeuzes
- **Opslag: SQLite** in `/app/data/communicatie.db` (persistent via het `./data`-volume, overleeft
  deploys). `sqlite3` zit in Python zelf — geen nieuwe dependency.
- **Mail lezen: IMAP** (`imaplib`, stdlib). Versturen: bestaande SMTP-`mailer`.
- **AI: Claude** (bestaande key). Concepten/samenvattingen via een zuinig model
  (bv. `claude-haiku-5-5`); de grote backfill-samenvattingen eventueel `claude-sonnet-5-5`.

## Datamodel (SQLite)
- **contacten** — de huurder-/contactrecords voor dit systeem. `id, naam, pand_slug, kamer,
  emails (lijst), telefoon, actief, samenvatting, samenvatting_bijgewerkt`. Geseed/gesynct vanuit de
  Huurders-sheet (niet vervangen). E-mail is de koppelsleutel; meerdere e-mails per contact mogelijk.
- **berichten** — `id, contact_id, pand_slug, kanaal (info/onderhoud/gmail-historie/handmatig),
  richting (in/uit), van, naar, cc, onderwerp, body, datum, bron, message_id (dedup), thread_id,
  klus_id (nullable)`.
- **klussen** (onderhoudstickets) — `id, contact_id, pand_slug, kamer, titel, omschrijving,
  status (open/vakman-ingeschakeld/wacht-op-huurder/afgerond), vakman_id (nullable), aangemaakt,
  afgerond_op, laatste_update`.
- **vakmannen** — `id, naam, vak (loodgieter/timmerman/ongedierte/…), email, telefoon, actief`.
- **acties** (goedkeuringswachtrij) — `id, type (concept-huurder/concept-vakman), contact_id,
  pand_slug, klus_id (nullable), ontvanger, concept_onderwerp, concept_body,
  status (open/goedgekeurd/verzonden/verworpen), aangemaakt, verzonden_op`.
- **Afgeleide signalen** (betaling achter, lege kamer, aflopend contract) zijn **geen tabellen** —
  die worden berekend uit de bestaande bronnen en in het centrale overzicht meegenomen.

## Schermen / UI
- **Huurders → klik op een naam → Communicatie.** Tijdlijn (berichten in/uit + onderhoud-events,
  gelabeld), AI-samenvatting bovenaan, knop "bericht loggen" en "antwoord opstellen" (AI-concept → wachtrij).
- **Onderhoud (centraal, nieuwe top-level pagina).** Alle tickets over álle panden, nieuwste boven,
  filter op pand/status. Klik → ticketdetail: gesprekshistorie + reageren + klusjesman aanvinken.
- **Pandkiezer-hoofdpagina → "Wat vraagt aandacht".** Eén centrale lijst over alle toegankelijke
  panden, met **type-labels** (onderhoud / communicatie / betaling / lege kamer / …). De losse
  indicatoren van de pand-landingspagina's worden hierheen gebundeld.
- **Beheer → Klusjesmannen.** Toevoegen/bewerken (naam, vak, e-mail, telefoon).
- **Goedkeuren (Openstaande acties).** Concept bekijken/bewerken → goedkeuren+versturen of verwerpen.
- **Beheer → Eenmalige Gmail-backfill.** Knop per huurder + "alle huurders in één keer", met voortgang.

## AI-stijlregels (hard)
Helder, direct, informeel-professioneel (studentenbeheer). **Geen** puntkomma's, **geen** lange
gedachtestreepjes. Vermijd AI-stopwoorden ("Uiteraard", "In afwachting van je reactie", "Ik sta voor
je klaar"). Afgedekt via (a) de systeemprompt én (b) een nacheck die `;`/`—` eruit haalt en
stopwoorden markeert.

---

## Fasering

### Fase 1 — Fundament + overzicht (meeste waarde, minste risico)
- SQLite-schema + DB-laag (los testbaar).
- `contacten` seeden vanuit de Huurders-sheet.
- Huurder-communicatiepagina: tijdlijn + AI-samenvatting + "bericht loggen" (handmatig/doorsturen) +
  "antwoord opstellen" (AI-concept → wachtrij).
- Onderhoud: centrale ticketlijst + ticketdetail + AI-conceptantwoord.
- Goedkeuringswachtrij ("Openstaande acties") + versturen via bestaande SMTP.
- Centrale "Wat vraagt aandacht"-lijst op de pandkiezer-hoofdpagina, met onderhoud- en comms-items;
  betaling/lege-kamer-signalen erin gehaakt zodra praktisch.
- Toegang per gebruiker.
- **Nog geen automatische mail** — berichten gaan er handmatig in.

### Fase 1b — Eenmalige Gmail-backfill (de "goede start")
- Lees jmmreckman@gmail.com via **IMAP** (Gmail app-wachtwoord, 2FA aan) in "All Mail".
- Per huurder zoeken op **e-mailadres** (verzonden + ontvangen), samenvatten via Claude, opslaan in DB
  (zowel ruwe berichten als samenvatting).
- "Alle huurders in één keer"-knop → loopt over alle huurders uit de sheet.
- **Achtergrondtaak met voortgang + hervatbaar** (niet een knop die de pagina laat hangen); per
  huurder één samenvattings-call i.p.v. per bericht (zuinig).
- Na afloop: Gmail app-wachtwoord weer **intrekken** (de doorlopende flow gebruikt info@/onderhoud@,
  niet je persoonlijke Gmail).
- Kanttekeningen: volume kan groot zijn → gechunkt draaien; sommige huurders hebben meerdere
  e-mailadressen (of een borgsteller/ouder) → meerdere e-mails per contact toestaan.

### Fase 2 — Automatische inname (dagelijks 09:00)
- IMAP-lezer van **info@** en **onderhoud@** (Strato), als geplande service (patroon van
  `dagelijkse-check`).
- **Voorgesteld matchen** aan huurder/pand op basis van afzender/body; twijfelgevallen in een
  "nog koppelen"-bakje dat je met één klik toewijst (niet blind automatisch).
- Nieuwe berichten in de tijdlijn/tickets; AI-concepten in de wachtrij.
- Benodigd: `onderhoud@` als eigen Strato-postvak (lezen via IMAP + versturen vanuit onderhoud@),
  IMAP-host + inloggegevens in `app.env`.

### Fase 3 — Klusjesmannen + dubbele mail
- Bij een ticket een klusjesman aanvinken →
  1. concept naar de huurder met de vakman-gegevens erin verwerkt;
  2. tweede concept naar de vakman: huurder [naam] op [adres] neemt contact op voor [reden];
     vaste instructies: factuur direct naar jou, en boven €150 eerst bellen (06-44021086).
- Beide concepten via de goedkeuringswachtrij.

---

## Wat jij moet regelen (per fase, geen haast)
- **Fase 1b:** Gmail **app-wachtwoord** aanmaken (2FA aan) voor jmmreckman@gmail.com. (Daarna intrekken.)
- **Fase 2:** `onderhoud@steenhub.nl` als Strato-postvak (bestaat die al?) + de **IMAP-host** van Strato
  + inloggegevens, zodat ik ze in `app.env` kan zetten.

## Open ontwerpkeuzes (bevestigen waar nodig)
- Contact-koppelsleutel = **e-mailadres**, met meerdere e-mails per huurder toegestaan. ✔ (akkoord)
- Backfill ook voor **oud-huurders** (Vertrokken-sheet), of alleen huidige? → nog te kiezen.
- Centrale lijst: wat telt als "afgehandeld" per type (bv. betaling afgevinkt, bericht beantwoord,
  ticket afgerond) → uitwerken in Fase 1.
