# Plan — Verwarmingsmonitoring & -sturing via Tado (steenhub)

> Status: **spike geslaagd, bouw nog niet begonnen.** Dit document beschrijft de
> architectuur en fasering. Geen persoonlijke/financiële data of concrete
> home-ID's/kamernamen in dit bestand (zie CLAUDE.md-kop) — die staan in de
> lopende chat / op de VPS.

## 1. Doel

Per pand (en per kamer/huurder) het stookgedrag monitoren en bijsturen, op een
manier die **de eigenaar aanstuurt en de huurder niet kan overrulen**:

- Per kamer temperatuur, setpoint en stookvermogen loggen → "gewoontes".
- Regels die de eigenaar instelt, bv. "non-stop 25° → mailtje", of "na X uur
  boven Y° elke uur een graad terug tot een basistemperatuur".
- De ketel wordt via Tado's Wireless Receiver meegestuurd (Tado doet dit zelf;
  wij sturen alleen setpoints/overlays per zone).

**Eerlijke beperking:** Tado levert temperatuur/setpoint/klepstand, géén gas-m³
per kamer. "Verbruik per huurder" is dus een *proxy* (klep-open-tijd), geen
exacte meting, tenzij er warmtekostenverdelers bij komen.

## 2. Wat de spike heeft bewezen (nov 2026)

Tegen de officiële Tado REST-API, met een los testscript:

- **Auth**: de device-code OAuth2-flow werkt (wachtwoord-grant is sinds maart
  2025 weg). Eenmalig goedkeuren in de browser → refresh token bewaren.
  - `client_id` = `1bb50063-6b0c-4d11-bd99-387f4a91cc46` (publiek, van Tado zelf).
  - `POST https://login.tado.com/oauth2/device_authorize?client_id=…&scope=offline_access`
  - `POST https://login.tado.com/oauth2/token` (grant_type device_code, dan refresh_token).
  - Access token ~kort; **refresh token roteert** (elk gebruik → nieuw token, oud vervalt;
    ~30 dagen ongebruikt geldig). Telkens de nieuwe opslaan.
  - **API is gratis** en staat los van het Auto-Assist-abonnement.
- **Lezen** (`https://my.tado.com/api/v2/`):
  - `GET /me` → `homes[].id` (één account kan meerdere homes dekken → meerdere panden).
  - `GET /homes/{home}/zones` → zones (id, naam, `devices[]` met serienr + `childLockEnabled`).
  - `GET /homes/{home}/zones/{zone}/state` → `sensorDataPoints.insideTemperature.celsius`,
    `setting.{power,temperature.celsius}` (temperatuur `None` als power OFF),
    `activityDataPoints.heatingPower.percentage`, en `overlay` (null = schema,
    anders handmatig met `termination.type` MANUAL/TIMER/TADO_MODE).
- **Sturen**:
  - `PUT /homes/{home}/zones/{zone}/overlay` met body
    `{"setting":{"type":"HEATING","power":"ON","temperature":{"celsius":X}},
      "termination":{"type":"TIMER","durationInSeconds":N}}` → HTTP 200, overlay actief.
    `termination` kan `MANUAL` (blijft staan) of `TIMER` (valt terug na N sec).
  - `DELETE /homes/{home}/zones/{zone}/overlay` → terug naar schema.
  - Getest op een eigen-huis-kamer: overlay gezet én daarna exact de
    oorspronkelijke stand hersteld. Non-destructief patroon werkt.
- **Child-lock**: per device uitleesbaar (`childLockEnabled`). We zetten 'm
  bewust **NIET** aan — dat blokkeert de fysieke knop, en huurders draaien juist
  uitsluitend aan die knop (zie §7).

## 3. Architectuur

In **steenhub** (niet een los subdomein): de koppeling met huurders, mailer,
pand-toegang en het "Wat vraagt aandacht"-dashboard is de hele waarde.

- **Web-UI** in `webapp/`: per-pand verwarmingspagina (live zones + historie per
  kamer), regel-instellingen, en het mapping-scherm. Achter de bestaande login +
  pand-toegang (Justin ziet alleen zijn panden).
- **`verwarming-check`-service**: aparte compose-service die hetzelfde image deelt
  (zoals `dagelijkse-check`/`mail-inname`), draait elke ~10-15 min: uitlezen,
  loggen, regels toepassen, flaggen. Geïsoleerd zodat een hik de huur-app niet
  raakt (en andersom).

## 4. Datamodel — eigen `verwarming.db` (SQLite in `state_dir`)

Los van `communicatie.db` zodat retentie/opschonen apart kan.

- **`zone_config`**: `pand_slug`, `tado_home_id`, `tado_zone_id`, `kamer` (of NULL
  = gedeeld/thermostaat), plus per-zone regelinstellingen (max_setpoint,
  afbouw-aan, afbouw-drempel, afbouw-na-uren, basis_temp, alert-drempel, …).
- **`sample`** (timeseries): `tado_home_id`, `tado_zone_id`, `ts`, `inside_celsius`,
  `setpoint_celsius`, `power`, `heating_pct`, `overlay_type`. Elke polling-ronde.
  Met een retentiebeleid (bv. ruwe samples N weken, daarna uurgemiddelden).
- **`tado_account`**: label → refresh-token-bestandspad (token zelf op de VPS,
  nooit in de db/git); mapping welke home-ID's bij welk account horen.

## 5. Mapping (het enige echt nieuwe UI-stuk)

Per pand: koppel een `tado_home_id`. Per zone kies je:
- → een **kamer** (en daarmee de huurder uit de Huurders-sheet), of
- → **gedeeld/thermostaat** (bv. hal, keuken, hoofdthermostaat) — geen huurder.

Optioneel per pand, net als de bunq-IBAN: een pand zónder Tado-koppeling slaat de
module netjes over.

## 6. Regel-engine (`verwarming-check`)

Per zone, instelbaar door de eigenaar (niet door de huurder):

- **Cap**: setpoint boven X → terugzetten (overlay).
- **Afbouw**: na Y uur boven Z° → elk uur een graad lager tot `basis_temp`, via
  een overlay met `TIMER` die elke ronde opnieuw/bijgewerkt wordt. Overlays met
  TIMER i.p.v. eeuwige MANUAL, zodat er nooit een "vastzittende" override blijft.
- **Sensor-sanity**: onmogelijke waarden (bv. >30° of <5°) → markeer als
  sensorprobleem en **stuur niet** (voorkomt alarmeren/stoken op ruis).
- **Alert**: setpoint ≥ drempel gedurende N uur → mail via de bestaande mailer +
  tegel op "Wat vraagt aandacht". Hergebruik van het goedkeuringswachtrij-patroon
  uit de communicatiemodule waar nuttig.

## 7. Eigenaar-controle — zónder de knop te blokkeren

**Child-lock gebruiken we NIET.** Dat zet de fysieke knop van de thermostaat
volledig vast (tegen kinderen). Huurders gebruiken geen app en draaien uitsluitend
aan die knop, dus die moet blijven werken.

In plaats daarvan: de knop blijft vrij, en de service **corrigeert achteraf via de
API**. Draait een huurder naar bv. 25°, dan ontstaat een MANUAL-overlay op die
zone; de volgende polling-ronde past `verwarming-check` de regel toe (cap terug,
afbouw starten, of alleen alerten). We voorkomen het draaien dus niet, we
corrigeren het — de knop blijft altijd werken.

Eerlijke consequentie: het werkt met de polling-tik mee (tot ~10-15 min), dus een
huurder krijgt kortstondig zijn hoge stand voordat de regel ingrijpt. Dichter
pollen verkleint dat raam (meer API-calls). Een harde cap die telkens terugdraait
voelt vijandig; **afbouw** (langzaam zakken na X uur hoog) is gebruiksvriendelijker
en meestal genoeg, met transparantie + mail erbij. (Tado kent voor zover bekend
geen harde max-stand op de knop zelf — te verifiëren bij het bouwen.)

## 8. Secrets & randvoorwaarden

- **Token** = per Tado-account refresh-token als VPS-bestand/env, nooit in git
  (zelfde regel als bunq/rclone). Eén account kan meerdere homes/panden dekken.
- **2 GB-VPS**: poll rustig (10-15 min; triviale last voor een handvol zones) en
  prune de timeseries. Geen zware/parallelle builds (zie CLAUDE.md §3).

## 9. Fasering

1. **Datalaag** (pure, los testbaar): `verwarming.db`-schema + CRUD + de
   regel-engine als pure functies (fakes voor API-calls).
2. **Tado-client** (`rotterdam_scanner`-stijl module): auth/refresh + read +
   overlay-set/release + child-lock. Token-opslag op de VPS.
3. **`verwarming-check`-service** + compose-entry + poll-loop + regels + mail.
4. **Web-UI**: mapping-scherm, per-pand verwarmingspagina met historie-grafiek,
   regel-instellingen; "Wat vraagt aandacht"-tegel. Pand-toegang respecteren.
5. Fijnafstelling: polling-frequentie vs. correctie-latency per pand afstemmen.

## 10. Open punten / nog te testen

- Correctie-latency: hoe snel pollen zodat caps/afbouw op tijd ingrijpen zonder
  te veel API-calls (en of een huurder die telkens terugdraait een praktijk-
  probleem is of een gespreksonderwerp).
- Gedrag van overlay-`TIMER` samen met bestaande handmatige overlays van huurders.
- Exacte retentie/aggregatie van de timeseries.
- Of we per pand één Tado-account hebben of meerdere (config moet beide aankunnen).
