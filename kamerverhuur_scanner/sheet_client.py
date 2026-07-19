"""Lezen en terugschrijven van de kamers/huurdersgegevens in Google Sheets.

Kolomindeling op het hoofdtabblad (rij 1 = koprij, data vanaf rij 2), aangesloten
op de bestaande huuradministratie-sheet:

    A Kamer | B Huurder | C Kale huurprijs | D Servicekosten | E Totale huur |
    F Contract einddatum | G Opmerking | H IBAN (nieuw, optioneel) |
    I Zoekwoord (nieuw, optioneel) | J Status (auto) | K Ontvangen bedrag (auto) |
    L Laatst gecontroleerd (auto) | M Beschikbaar (nieuw, JA/NEE) |
    N Advertentie omschrijving (nieuw) | O Advertentie map-ID (nieuw, auto) |
    P Mail (nieuw, optioneel) | Q Telefoonnummer (nieuw, optioneel) |
    R Geboortedatum (nieuw, optioneel, tbv huurcontract) |
    S Geboorteplaats (nieuw, optioneel, tbv huurcontract) |
    T Studentnummer (nieuw, optioneel, tbv huurcontract) |
    U Studierichting (nieuw, optioneel, tbv huurcontract) |
    V Borgsteller naam (nieuw, optioneel, tbv huurcontract) |
    W Borgsteller relatie (nieuw, optioneel, tbv huurcontract) |
    X Contract startdatum (nieuw, optioneel, tbv huurcontract EN de
      betaalgeschiedenis: backfill_geschiedenis() vult vanaf deze maand aan
      i.p.v. een vast aantal maanden terug) |
    Y Borg (nieuw, optioneel) - waarborgsom die in de instapmaand naast de
      (eventueel pro-rata) huur binnenkomt, zodat die maand niet als "te veel
      ontvangen" wordt gezien |
    Z Advertentie prijs (nieuw, optioneel) | AA Advertentie oppervlakte
      (nieuw, optioneel, vrije tekst) | AB Advertentie beschikbaar per
      (nieuw, optioneel, vrije tekst) | AC Advertentie beschikbaar tot
      (nieuw, optioneel, vrije tekst) | AD Advertentie borg (nieuw, optioneel)

Kolommen Z t/m AD zijn puur voor de publieke aanbodpagina/advertentie (zie
webapp/ads.py) - bewust losgekoppeld van "Totale huur" (E) en "Borg" (Y),
want een geadverteerde kamer heeft vaak nog geen huurder (en dus geen
ingevulde Y) en de geadverteerde prijs mag afwijken van de huur van de
HUIDIGE/vorige huurder. Leeg = de aanbodpagina valt terug op "Totale huur"
voor de prijs, en laat de overige regels gewoon weg.

"Totale huur" (kolom E) is het bedrag dat via bunq moet binnenkomen. Een rij met
een lege Huurder maar een ingevulde Kamer betekent: kamer staat leeg. Een rij
waarvan de Kamer-kolom "totalen"/"totaal" is (de somrij onderaan) wordt genegeerd.

Daarnaast is er een "Historie" tabblad (wordt aangemaakt als het nog niet
bestaat) met kolommen: Maand | Kamer | Huurder | Verwacht | Ontvangen |
Status | Betaaldatum - precies 1 regel per kamer per kalendermaand
("jjjj-mm"). Elke controle werkt de regel van de huidige maand bij (in
plaats van een nieuwe regel toe te voegen), zodat vaker controleren binnen
dezelfde maand de betrouwbaarheidsscore niet vertekent. "Betaaldatum" is de
datum van de (laatste) gematchte betaling, niet de controledatum - zo blijft
zichtbaar of iemand laat betaalde, ook al is de kamer inmiddels gewoon
"Betaald".

En een "Aanmeldingen" tabblad (ook automatisch aangemaakt) waar reacties op de
publieke aanbodpagina in terechtkomen - zie webapp/aanbod.py.

En een "Bezichtigingen" tabblad (ook automatisch aangemaakt) met elke
bevestigde bezichtiging (datum, tijdslot, wie, hoe) - zie webapp/bezichtiging.py.
Puur een log; hierdoor kan "Bezichtigers toevoegen aan bestaande lijst" een
eerder geplande dag terugvinden en er verder op aansluiten.

En een "Vertrokken" tabblad (ook automatisch aangemaakt) met een
momentopname van elke huurder die een kamer verlaat doordat er een andere
naam voor die kamer wordt ingevoerd (via een nieuw huurcontract of
handmatig bij Huurders bewerken) - blijft nog een maand na hun
contracteinddatum zichtbaar op de Huurders-pagina, zie
archiveer_vertrokken_huurder()/get_recent_vertrokken_huurders() hieronder.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import gspread

from .config import Config
from .models import Aanmelding, HistorieRegel, Pand, Payment, Status, Tenant, TenantResult, VertrokkenHuurder
from .utils import parse_bedrag

# Hoelang een vertrokken huurder na hun contracteinddatum nog gearchiveerd
# blijft getoond op de Huurders-pagina - een grove "1 maand" (geen precieze
# kalendermaand-berekening nodig voor een archiveringstermijn).
_VERTROKKEN_ZICHTBAAR_DAGEN = 31

COL_KAMER = 1
COL_NAAM = 2
COL_KALE_HUURPRIJS = 3
COL_SERVICEKOSTEN = 4
COL_VERWACHT = 5
COL_CONTRACT_EINDDATUM = 6
COL_OPMERKING = 7
COL_IBAN = 8
COL_ZOEKWOORD = 9
COL_STATUS = 10
COL_ONTVANGEN = 11
COL_LAATST_GECONTROLEERD = 12
COL_BESCHIKBAAR = 13
COL_ADVERTENTIE_OMSCHRIJVING = 14
COL_ADVERTENTIE_MAP_ID = 15
COL_EMAIL = 16
COL_TELEFOONNUMMER = 17
COL_GEBOORTEDATUM = 18
COL_GEBOORTEPLAATS = 19
COL_STUDENTNUMMER = 20
COL_STUDIERICHTING = 21
COL_BORGSTELLER_NAAM = 22
COL_BORGSTELLER_RELATIE = 23
COL_CONTRACT_STARTDATUM = 24
COL_BORG = 25
COL_ADVERTENTIE_PRIJS = 26
COL_ADVERTENTIE_OPPERVLAKTE = 27
COL_ADVERTENTIE_BESCHIKBAAR_PER = 28
COL_ADVERTENTIE_BESCHIKBAAR_TOT = 29
COL_ADVERTENTIE_BORG = 30
COL_COMMUNICATIE_PROFIEL = 31

HEADER_ROW = 1
_SOMRIJ_LABELS = {"totalen", "totaal"}

_HISTORIE_HEADER = ["Maand", "Kamer", "Huurder", "Verwacht bedrag", "Ontvangen bedrag", "Status", "Betaaldatum"]
_MAAND_PATROON = re.compile(r"\d{4}-\d{2}")
# Specifiek dag "01": zo slaat Google Sheets een geschreven "jjjj-mm" soms
# zelf op als datum (de dag wordt daarbij altijd op de 1e gezet). Een ANDERE
# dag (bv. "03-07-2026") is dus geen slachtoffer van die auto-conversie, maar
# een echt oud/onherkenbaar rijformaat - dat moet nog steeds genegeerd worden.
_MAAND_ALS_DATUM_PATROON = re.compile(r"01-(\d{2})-(\d{4})")


def _normaliseer_maand(tekst: str) -> str | None:
    """Zet een 'Maand'-waarde uit de Historie-sheet om naar het canonieke
    'jjjj-mm'-formaat. Nodig omdat Google Sheets een geschreven waarde als
    "2026-06" soms zelf herkent als datum en opslaat/toont als "01-06-2026"
    (ondanks value_input_option=RAW bij nieuwe schrijfacties, voor rijen die
    van vóór die fix dateren) - zonder deze normalisatie worden zulke rijen
    onterecht als 'onherkenbaar oud formaat' overgeslagen. Geeft None terug
    als de tekst geen van beide formaten is."""
    tekst = tekst.strip()
    if _MAAND_PATROON.fullmatch(tekst):
        return tekst
    match = _MAAND_ALS_DATUM_PATROON.fullmatch(tekst)
    if match:
        maand, jaar = match.groups()
        return f"{jaar}-{maand}"
    return None


def _genezen_maand_kolom(row: list[str]) -> list[str]:
    """Vervangt de 'Maand'-cel van een Historie-rij door de genormaliseerde
    'jjjj-mm'-vorm, als die herkend wordt - laat de rij ongewijzigd als de
    tekst geen van beide bekende formaten is (voorkomt dataverlies bij een
    echt onherkenbare/handmatig aangepaste rij)."""
    genormaliseerd = _normaliseer_maand(row[0]) if row else None
    if not genormaliseerd:
        return row
    return [genormaliseerd, *row[1:]]


def _herschrijf_historie(ws, header: list[str], data_rows: list[list[str]]) -> None:
    """Overschrijft de hele Historie-worksheet met deze koprij + databegin -
    gebruikt door dedupliceer_geschiedenis() en
    verwijder_geschiedenis_voor_instapdatum() om regels te verwijderen/
    genezen (gspread heeft geen 'verwijder deze rij'-aanroep). RAW voorkomt
    dat Google Sheets een waarde als "2026-06" zelf als datum omzet."""
    ws.clear()
    ws.append_row(header, value_input_option="RAW")
    if data_rows:
        ws.append_rows(data_rows, value_input_option="RAW")


_AANMELDINGEN_HEADER = [
    "Datum", "Kamer", "Naam", "Email", "Telefoon", "Huidig adres", "Studie",
    "Studentnummer", "Gewenste ingangsdatum", "Gewenste huurduur",
    "Inkomstenbron", "Inkomsten (bedrag)", "Borgsteller", "Bezichtiging",
    "Video-bel nummer", "Bewijs inschrijving",
    "Borgsteller naam", "Borgsteller relatie", "Borgsteller email",
]

_BEZICHTIGINGEN_HEADER = [
    "Datum", "Tijd start", "Tijd eind", "Kamer", "Naam", "Email", "Telefoon",
    "Manier", "Bel nummer", "Bevestigd op",
]

_COMMUNICATIE_HEADER = ["Datum", "Kamer", "Huurder", "Richting", "Onderwerp", "Tekst"]

_VERTROKKEN_HEADER = ["Kamer", "Naam", "Mail", "Telefoonnummer", "Contract einddatum", "Vertrokken op"]


def _optioneel(waarde: str) -> str | None:
    return waarde.strip() or None


def _naar_ja_nee(waarde: bool) -> str:
    return "JA" if waarde else "NEE"


def _naar_bool(waarde: str) -> bool:
    return waarde.strip().upper() in {"JA", "TRUE", "WAAR", "1"}


def _parse_contract_einddatum(tekst: str) -> date | None:
    """Contract einddatum (kolom F) is vrije tekst - kan een datum
    dd-mm-jjjj zijn, of iets als 'onbepaalde tijd'. Geeft None terug als het
    geen (herkenbare) datum is."""
    try:
        return datetime.strptime(tekst.strip(), "%d-%m-%Y").date()
    except ValueError:
        return None


def _laatste_betaaldatum(betalingen: list[Payment]) -> date | None:
    return max((p.datum for p in betalingen), default=None)


class SheetClient:
    def __init__(self, config: Config, pand: Pand):
        self._pand = pand
        gc = gspread.service_account(filename=config.google_service_account_file)
        self._spreadsheet = gc.open_by_key(pand.google_sheet_id)
        self._worksheet = self._spreadsheet.worksheet(pand.google_sheet_worksheet)

    def get_kamers(self) -> list[Tenant]:
        """Geeft alle kamers terug, inclusief leegstaande (lege huurder, wel een kamernaam)."""
        rows = self._worksheet.get_all_values()
        kamers: list[Tenant] = []
        for offset, row in enumerate(rows[HEADER_ROW:]):
            row_index = HEADER_ROW + 1 + offset
            row = row + [""] * (COL_COMMUNICATIE_PROFIEL - len(row))
            kamer = row[COL_KAMER - 1].strip()
            if not kamer or kamer.lower() in _SOMRIJ_LABELS:
                continue  # lege rij of somrij ("Totalen") overslaan
            kamers.append(
                Tenant(
                    row_index=row_index,
                    naam=row[COL_NAAM - 1].strip(),
                    kamer=kamer,
                    verwacht_bedrag=parse_bedrag(row[COL_VERWACHT - 1]),
                    iban=(row[COL_IBAN - 1].strip().replace(" ", "").upper() or None),
                    zoekwoord=_optioneel(row[COL_ZOEKWOORD - 1]),
                    kale_huurprijs=parse_bedrag(row[COL_KALE_HUURPRIJS - 1]) if row[COL_KALE_HUURPRIJS - 1].strip() else None,
                    servicekosten=parse_bedrag(row[COL_SERVICEKOSTEN - 1]) if row[COL_SERVICEKOSTEN - 1].strip() else None,
                    contract_einddatum=_optioneel(row[COL_CONTRACT_EINDDATUM - 1]),
                    opmerking=_optioneel(row[COL_OPMERKING - 1]),
                    beschikbaar=_naar_bool(row[COL_BESCHIKBAAR - 1]),
                    advertentie_omschrijving=_optioneel(row[COL_ADVERTENTIE_OMSCHRIJVING - 1]),
                    advertentie_map_id=_optioneel(row[COL_ADVERTENTIE_MAP_ID - 1]),
                    email=_optioneel(row[COL_EMAIL - 1]),
                    telefoonnummer=_optioneel(row[COL_TELEFOONNUMMER - 1]),
                    geboortedatum=_optioneel(row[COL_GEBOORTEDATUM - 1]),
                    geboorteplaats=_optioneel(row[COL_GEBOORTEPLAATS - 1]),
                    studentnummer=_optioneel(row[COL_STUDENTNUMMER - 1]),
                    studierichting=_optioneel(row[COL_STUDIERICHTING - 1]),
                    borgsteller_naam=_optioneel(row[COL_BORGSTELLER_NAAM - 1]),
                    borgsteller_relatie=_optioneel(row[COL_BORGSTELLER_RELATIE - 1]),
                    contract_startdatum=_optioneel(row[COL_CONTRACT_STARTDATUM - 1]),
                    borg_bedrag=parse_bedrag(row[COL_BORG - 1]) if row[COL_BORG - 1].strip() else None,
                    advertentie_prijs=(
                        parse_bedrag(row[COL_ADVERTENTIE_PRIJS - 1]) if row[COL_ADVERTENTIE_PRIJS - 1].strip() else None
                    ),
                    advertentie_oppervlakte=_optioneel(row[COL_ADVERTENTIE_OPPERVLAKTE - 1]),
                    advertentie_beschikbaar_per=_optioneel(row[COL_ADVERTENTIE_BESCHIKBAAR_PER - 1]),
                    advertentie_beschikbaar_tot=_optioneel(row[COL_ADVERTENTIE_BESCHIKBAAR_TOT - 1]),
                    advertentie_borg=(
                        parse_bedrag(row[COL_ADVERTENTIE_BORG - 1]) if row[COL_ADVERTENTIE_BORG - 1].strip() else None
                    ),
                    communicatie_profiel=_optioneel(row[COL_COMMUNICATIE_PROFIEL - 1]),
                )
            )
        return kamers

    def get_tenants(self) -> list[Tenant]:
        """Geeft alleen de kamers terug die op dit moment een huurder hebben."""
        return [k for k in self.get_kamers() if k.naam]

    def update_kamer(
        self,
        row_index: int,
        naam: str,
        kamer: str,
        verwacht_bedrag: Decimal,
        iban: str | None,
        zoekwoord: str | None,
        kale_huurprijs: Decimal | None = None,
        servicekosten: Decimal | None = None,
        contract_einddatum: str | None = None,
        opmerking: str | None = None,
        email: str | None = None,
        telefoonnummer: str | None = None,
        geboortedatum: str | None = None,
        geboorteplaats: str | None = None,
        studentnummer: str | None = None,
        studierichting: str | None = None,
        borgsteller_naam: str | None = None,
        borgsteller_relatie: str | None = None,
        contract_startdatum: str | None = None,
        borg_bedrag: Decimal | None = None,
    ) -> None:
        self._zorg_voor_voldoende_kolommen(COL_BORG)
        updates = [
            {"range": self._a1(row_index, COL_KAMER), "values": [[kamer]]},
            {"range": self._a1(row_index, COL_NAAM), "values": [[naam]]},
            {"range": self._a1(row_index, COL_KALE_HUURPRIJS), "values": [[self._bedrag_of_leeg(kale_huurprijs)]]},
            {"range": self._a1(row_index, COL_SERVICEKOSTEN), "values": [[self._bedrag_of_leeg(servicekosten)]]},
            {
                "range": self._a1(row_index, COL_VERWACHT),
                "values": [[f"{verwacht_bedrag:.2f}".replace(".", ",")]],
            },
            {"range": self._a1(row_index, COL_CONTRACT_EINDDATUM), "values": [[contract_einddatum or ""]]},
            {"range": self._a1(row_index, COL_OPMERKING), "values": [[opmerking or ""]]},
            {"range": self._a1(row_index, COL_IBAN), "values": [[iban or ""]]},
            {"range": self._a1(row_index, COL_ZOEKWOORD), "values": [[zoekwoord or ""]]},
            {"range": self._a1(row_index, COL_EMAIL), "values": [[email or ""]]},
            {"range": self._a1(row_index, COL_TELEFOONNUMMER), "values": [[telefoonnummer or ""]]},
            {"range": self._a1(row_index, COL_GEBOORTEDATUM), "values": [[geboortedatum or ""]]},
            {"range": self._a1(row_index, COL_GEBOORTEPLAATS), "values": [[geboorteplaats or ""]]},
            {"range": self._a1(row_index, COL_STUDENTNUMMER), "values": [[studentnummer or ""]]},
            {"range": self._a1(row_index, COL_STUDIERICHTING), "values": [[studierichting or ""]]},
            {"range": self._a1(row_index, COL_BORGSTELLER_NAAM), "values": [[borgsteller_naam or ""]]},
            {"range": self._a1(row_index, COL_BORGSTELLER_RELATIE), "values": [[borgsteller_relatie or ""]]},
            {"range": self._a1(row_index, COL_CONTRACT_STARTDATUM), "values": [[contract_startdatum or ""]]},
            {"range": self._a1(row_index, COL_BORG), "values": [[self._bedrag_of_leeg(borg_bedrag)]]},
        ]
        self._worksheet.batch_update(updates, value_input_option="USER_ENTERED")

    def update_aanbod(
        self,
        row_index: int,
        beschikbaar: bool,
        omschrijving: str | None,
        map_id: str | None,
        prijs: Decimal | None = None,
        oppervlakte: str | None = None,
        beschikbaar_per: str | None = None,
        beschikbaar_tot: str | None = None,
        borg: Decimal | None = None,
    ) -> None:
        # Anders dan bij nieuwe RIJEN (die de Sheets API vanzelf aanmaakt),
        # breidt de API het aantal KOLOMMEN niet automatisch uit - schrijven
        # voorbij het huidige grid (bv. een sheet die nog nooit tot kolom AD
        # is uitgebreid) faalt anders met "exceeds grid limits".
        self._zorg_voor_voldoende_kolommen(COL_ADVERTENTIE_BORG)
        updates = [
            {"range": self._a1(row_index, COL_BESCHIKBAAR), "values": [[_naar_ja_nee(beschikbaar)]]},
            {"range": self._a1(row_index, COL_ADVERTENTIE_OMSCHRIJVING), "values": [[omschrijving or ""]]},
            {"range": self._a1(row_index, COL_ADVERTENTIE_MAP_ID), "values": [[map_id or ""]]},
            {"range": self._a1(row_index, COL_ADVERTENTIE_PRIJS), "values": [[self._bedrag_of_leeg(prijs)]]},
            {"range": self._a1(row_index, COL_ADVERTENTIE_OPPERVLAKTE), "values": [[oppervlakte or ""]]},
            {"range": self._a1(row_index, COL_ADVERTENTIE_BESCHIKBAAR_PER), "values": [[beschikbaar_per or ""]]},
            {"range": self._a1(row_index, COL_ADVERTENTIE_BESCHIKBAAR_TOT), "values": [[beschikbaar_tot or ""]]},
            {"range": self._a1(row_index, COL_ADVERTENTIE_BORG), "values": [[self._bedrag_of_leeg(borg)]]},
        ]
        self._worksheet.batch_update(updates, value_input_option="USER_ENTERED")

    def update_communicatie_profiel(self, row_index: int, profiel: str) -> None:
        self._zorg_voor_voldoende_kolommen(COL_COMMUNICATIE_PROFIEL)
        self._worksheet.batch_update(
            [{"range": self._a1(row_index, COL_COMMUNICATIE_PROFIEL), "values": [[profiel]]}],
            value_input_option="USER_ENTERED",
        )

    def _zorg_voor_voldoende_kolommen(self, min_cols: int) -> None:
        """Breidt het grid van het hoofdtabblad uit als dat nog niet genoeg
        kolommen heeft. Anders dan bij nieuwe rijen (die gewoon ontstaan door
        ze te schrijven) breidt de Sheets API het aantal kolommen NIET vanzelf
        uit bij een schrijfactie voorbij de huidige grid-afmetingen - dat
        geeft dan een "exceeds grid limits"-fout in plaats van gewoon te
        werken (bv. een sheet die (nog) nooit tot kolom AD is uitgebreid)."""
        if self._worksheet.col_count < min_cols:
            self._worksheet.resize(cols=min_cols)

    def write_results(self, results: list[TenantResult]) -> None:
        now = datetime.now().strftime("%d-%m-%Y %H:%M")
        updates = []
        for result in results:
            row = result.tenant.row_index
            updates.append({"range": self._a1(row, COL_STATUS), "values": [[result.status.value]]})
            updates.append(
                {
                    "range": self._a1(row, COL_ONTVANGEN),
                    "values": [[f"{result.ontvangen_bedrag:.2f}".replace(".", ",")]],
                }
            )
            updates.append({"range": self._a1(row, COL_LAATST_GECONTROLEERD), "values": [[now]]})
        if updates:
            self._worksheet.batch_update(updates, value_input_option="USER_ENTERED")

    def upsert_history(self, results: list[TenantResult], maand: str) -> None:
        """Werkt de historieregel van elke huurder voor deze kalendermaand bij
        (of maakt 'm aan als die nog niet bestaat) - nooit een tweede regel
        voor dezelfde (kamer, maand)-combinatie, ook niet bij vaker
        controleren binnen dezelfde maand.

        De huurdersnaam van een BESTAANDE regel wordt na de eerste keer
        wegschrijven bevroren (alleen bedrag/status/betaaldatum worden nog
        bijgewerkt) - anders overschrijft het invullen van een nieuwe huurder
        voor volgende maand (vooruitlopend op een instapdatum in de
        toekomst) per ongeluk de geschiedenis van de nog lopende maand van de
        vertrekkende huurder, terwijl de matching zelf (op bedrag/IBAN) prima
        blijft werken. Alleen bij een gloednieuwe regel wordt de dan-actuele
        naam gebruikt.

        Schrijft met value_input_option=RAW (i.p.v. USER_ENTERED), anders
        herkent Google Sheets een waarde als "2026-06" soms zelf als datum en
        slaat 'm op (en toont 'm) als "01-06-2026" - dan vindt deze functie
        bij een volgende aanroep de bestaande rij niet meer terug (andere
        tekst) en blijven er dubbele regels bijkomen. Bestaande rijen die al
        zo'n datum-vermomming hebben (van vóór deze fix) worden bij het
        opzoeken alsnog herkend via _normaliseer_maand()."""
        ws = self._history_worksheet()
        bestaande = ws.get_all_values()
        # Sleutel op (kamer, maand) samen - alleen op kamer sleutelen liet bij
        # meerdere bestaande maanden voor dezelfde kamer alleen de laatst
        # geziene rij over, waardoor eerdere maanden niet meer gevonden
        # werden en er per ongeluk dubbele regels bijkwamen.
        rij_voor_kamer_maand = {
            (row[1].strip(), genormaliseerd): i
            for i, row in enumerate(bestaande[1:], start=2)
            if len(row) > 1 and (genormaliseerd := _normaliseer_maand(row[0]))
        }

        updates = []
        nieuwe_rijen = []
        for r in results:
            betaaldatum = _laatste_betaaldatum(r.gematchte_betalingen)
            rij_index = rij_voor_kamer_maand.get((r.tenant.kamer, maand))
            bestaande_rij = bestaande[rij_index - 1] if rij_index else None
            huurder = bestaande_rij[2] if bestaande_rij and len(bestaande_rij) > 2 and bestaande_rij[2] else r.tenant.naam
            rij = [
                maand,
                r.tenant.kamer,
                huurder,
                f"{r.tenant.verwacht_bedrag:.2f}".replace(".", ","),
                f"{r.ontvangen_bedrag:.2f}".replace(".", ","),
                r.status.value,
                betaaldatum.strftime("%d-%m-%Y") if betaaldatum else "",
            ]
            if rij_index:
                updates.append({"range": f"A{rij_index}:G{rij_index}", "values": [rij]})
            else:
                nieuwe_rijen.append(rij)

        if updates:
            ws.batch_update(updates, value_input_option="RAW")
        if nieuwe_rijen:
            ws.append_rows(nieuwe_rijen, value_input_option="RAW")

    def verwijder_geschiedenis_voor_instapdatum(self, kamer: str, huurder: str, oudste_geldige_maand: str) -> int:
        """Verwijdert Historie-regels van déze huurder op déze kamer van vóór
        `oudste_geldige_maand` (formaat 'jjjj-mm') - regels die zijn
        ontstaan doordat een eerdere 'Betaalgeschiedenis aanvullen' de
        Contract-startdatum niet kon lezen (bv. een datumformaat dat toen nog
        niet werd herkend) en daardoor per ongeluk terugrekende tot vóór de
        werkelijke instapdatum van de huurder. Regels van een eerdere huurder
        op dezelfde kamer (ander 'Huurder'-veld) blijven onaangeroerd. Geeft
        het aantal verwijderde regels terug."""
        ws = self._history_worksheet()
        rows = ws.get_all_values()
        if len(rows) <= 1:
            return 0
        header, data_rows = rows[0], rows[1:]

        schoon = [
            _genezen_maand_kolom(row) for row in data_rows
            if not (
                len(row) > 2 and row[1].strip() == kamer and row[2].strip() == huurder
                and (genormaliseerd := _normaliseer_maand(row[0])) and genormaliseerd < oudste_geldige_maand
            )
        ]
        verwijderd = len(data_rows) - len(schoon)
        if verwijderd > 0:
            _herschrijf_historie(ws, header, schoon)
        return verwijderd

    def dedupliceer_geschiedenis(self) -> int:
        """Verwijdert dubbele Historie-regels voor dezelfde (kamer, maand) -
        combinatie (kon ontstaan door een bug in upsert_history) en houdt de
        ONDERSTE (dus laatst weggeschreven, meest recente) regel. Geeft het
        aantal verwijderde regels terug. Herstelt daarbij ook meteen de
        'Maand'-kolom van rijen die Google Sheets ooit als datum heeft
        opgeslagen (bv. "01-06-2026" i.p.v. "2026-06"), zie _normaliseer_maand()."""
        ws = self._history_worksheet()
        rows = ws.get_all_values()
        if len(rows) <= 1:
            return 0
        header, data_rows = rows[0], rows[1:]

        laatste_per_sleutel: dict[tuple[str, str], list[str]] = {}
        volgorde: list[tuple[str, str]] = []
        for row in data_rows:
            row = _genezen_maand_kolom(row + [""] * (7 - len(row)))
            sleutel = (row[1].strip(), row[0].strip())
            if sleutel not in laatste_per_sleutel:
                volgorde.append(sleutel)
            laatste_per_sleutel[sleutel] = row  # overschrijft met de laatst geziene (= onderste) rij

        schoon = [laatste_per_sleutel[sleutel] for sleutel in volgorde]
        verwijderd = len(data_rows) - len(schoon)
        moest_genezen = any(row[0].strip() != _normaliseer_maand(row[0]) for row in data_rows if _normaliseer_maand(row[0]))
        if verwijderd > 0 or moest_genezen:
            _herschrijf_historie(ws, header, schoon)
        return verwijderd

    def get_geschiedenis(self, kamer: str) -> list[HistorieRegel]:
        ws = self._history_worksheet()
        rows = ws.get_all_values()[1:]  # koprij overslaan
        regels: list[HistorieRegel] = []
        for row in rows:
            row = row + [""] * (7 - len(row))
            genormaliseerde_maand = _normaliseer_maand(row[0])
            if row[1].strip() != kamer or not genormaliseerde_maand:
                continue  # andere kamer, of een regel van vóór deze indeling (oud datumformaat)
            try:
                regels.append(
                    HistorieRegel(
                        maand=genormaliseerde_maand,
                        kamer=row[1].strip(),
                        huurder=row[2].strip(),
                        verwacht_bedrag=parse_bedrag(row[3]),
                        ontvangen_bedrag=parse_bedrag(row[4]),
                        status=Status(row[5].strip()),
                        betaaldatum=datetime.strptime(row[6].strip(), "%d-%m-%Y").date() if row[6].strip() else None,
                    )
                )
            except ValueError:
                continue  # onverwacht/onvolledig rijformaat overslaan
        regels.sort(key=lambda r: r.maand)
        return regels

    def _history_worksheet(self):
        try:
            return self._spreadsheet.worksheet(self._pand.history_worksheet)
        except gspread.exceptions.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(
                title=self._pand.history_worksheet, rows=1000, cols=len(_HISTORIE_HEADER)
            )
            ws.append_row(_HISTORIE_HEADER, value_input_option="USER_ENTERED")
            return ws

    def add_aanmelding(self, kamer: str, aanmelding: Aanmelding) -> None:
        ws = self._aanmeldingen_worksheet()
        row = [
            datetime.now().strftime("%d-%m-%Y %H:%M"),
            kamer,
            aanmelding.naam,
            aanmelding.email,
            aanmelding.telefoon,
            aanmelding.huidig_adres,
            aanmelding.studie,
            aanmelding.studentnummer,
            aanmelding.gewenste_ingangsdatum,
            aanmelding.gewenste_huurduur,
            aanmelding.inkomstenbron,
            aanmelding.inkomsten_bedrag,
            aanmelding.borgsteller,
            aanmelding.bezichtiging,
            aanmelding.videobel_nummer,
            aanmelding.bewijs_inschrijving_link,
            aanmelding.borgsteller_naam,
            aanmelding.borgsteller_relatie,
            aanmelding.borgsteller_email,
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")

    def get_aanmeldingen(self) -> list[list[str]]:
        ws = self._aanmeldingen_worksheet()
        rows = ws.get_all_values()[1:]  # koprij overslaan
        aantal_kolommen = len(_AANMELDINGEN_HEADER)
        return [
            row + [""] * (aantal_kolommen - len(row))
            for row in rows if any(cel.strip() for cel in row)
        ]

    def wis_aanmeldingen(self) -> None:
        ws = self._aanmeldingen_worksheet()
        ws.clear()
        ws.append_row(_AANMELDINGEN_HEADER, value_input_option="USER_ENTERED")

    def _aanmeldingen_worksheet(self):
        try:
            return self._spreadsheet.worksheet(self._pand.aanmeldingen_worksheet)
        except gspread.exceptions.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(
                title=self._pand.aanmeldingen_worksheet, rows=1000, cols=len(_AANMELDINGEN_HEADER)
            )
            ws.append_row(_AANMELDINGEN_HEADER, value_input_option="USER_ENTERED")
            return ws

    def add_bezichtiging(self, datum_iso: str, afspraak: dict) -> None:
        ws = self._bezichtigingen_worksheet()
        ws.append_row(
            [
                datum_iso, afspraak["tijd_start"], afspraak["tijd_eind"], afspraak["kamer"],
                afspraak["naam"], afspraak["email"], afspraak["telefoon"], afspraak["bezichtiging"],
                afspraak["bel_nummer"], datetime.now().strftime("%d-%m-%Y %H:%M"),
            ],
            value_input_option="USER_ENTERED",
        )

    def get_bezichtigingen(self) -> list[list[str]]:
        ws = self._bezichtigingen_worksheet()
        rows = ws.get_all_values()[1:]  # koprij overslaan
        aantal_kolommen = len(_BEZICHTIGINGEN_HEADER)
        return [
            row + [""] * (aantal_kolommen - len(row))
            for row in rows if any(cel.strip() for cel in row)
        ]

    def _bezichtigingen_worksheet(self):
        try:
            return self._spreadsheet.worksheet(self._pand.bezichtigingen_worksheet)
        except gspread.exceptions.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(
                title=self._pand.bezichtigingen_worksheet, rows=1000, cols=len(_BEZICHTIGINGEN_HEADER)
            )
            ws.append_row(_BEZICHTIGINGEN_HEADER, value_input_option="USER_ENTERED")
            return ws

    def add_communicatie(self, kamer: str, huurder_naam: str, richting: str, onderwerp: str, tekst: str) -> None:
        ws = self._communicatie_worksheet()
        ws.append_row(
            [datetime.now().strftime("%d-%m-%Y %H:%M"), kamer, huurder_naam, richting, onderwerp, tekst],
            value_input_option="USER_ENTERED",
        )

    def get_communicatie(self, kamer: str) -> list[list[str]]:
        """Geeft de communicatiegeschiedenis voor deze kamer terug, oudste eerst."""
        ws = self._communicatie_worksheet()
        rows = ws.get_all_values()[1:]  # koprij overslaan
        aantal_kolommen = len(_COMMUNICATIE_HEADER)
        return [
            row + [""] * (aantal_kolommen - len(row))
            for row in rows if any(cel.strip() for cel in row) and row[1].strip() == kamer
        ]

    def _communicatie_worksheet(self):
        try:
            return self._spreadsheet.worksheet(self._pand.communicatie_worksheet)
        except gspread.exceptions.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(
                title=self._pand.communicatie_worksheet, rows=1000, cols=len(_COMMUNICATIE_HEADER)
            )
            ws.append_row(_COMMUNICATIE_HEADER, value_input_option="USER_ENTERED")
            return ws

    def archiveer_vertrokken_huurder(self, kamer: Tenant) -> None:
        """Legt een momentopname vast van een huurder die een kamer verlaat
        (aangeroepen vlak vóórdat hun gegevens door een nieuwe/andere naam
        worden overschreven) - blijft nog een tijdje zichtbaar op de
        Huurders-pagina, zie get_recent_vertrokken_huurders(). Doet niets als
        de kamer al leeg stond (geen naam om te archiveren)."""
        if not kamer.naam:
            return
        ws = self._vertrokken_worksheet()
        row = [
            kamer.kamer, kamer.naam, kamer.email or "", kamer.telefoonnummer or "",
            kamer.contract_einddatum or "", date.today().strftime("%d-%m-%Y"),
        ]
        ws.append_row(row, value_input_option="RAW")

    def _alle_vertrokken_huurders_ruw(self) -> list[VertrokkenHuurder]:
        """Alle ooit gearchiveerde vertrokken huurders, nieuwste eerst - de
        volledige, permanente lijst (zie get_alle_vertrokken_huurders()) die
        ook get_recent_vertrokken_huurders() als basis gebruikt voor zijn
        tijdelijke filter."""
        ws = self._vertrokken_worksheet()
        rows = ws.get_all_values()[1:]  # koprij overslaan
        resultaat = []
        for i, row in enumerate(rows):
            row_index = i + 2  # +1 voor de koprij, +1 voor 1-gebaseerde rijnummers
            row = row + [""] * (6 - len(row))
            kamer, naam, mail, telefoon, contract_einddatum, vertrokken_op_tekst = (c.strip() for c in row[:6])
            if not naam:
                continue
            try:
                vertrokken_op = datetime.strptime(vertrokken_op_tekst, "%d-%m-%Y").date()
            except ValueError:
                continue  # onherkenbare/handmatig aangepaste rij overslaan
            resultaat.append(VertrokkenHuurder(
                kamer=kamer, naam=naam, email=mail or None, telefoonnummer=telefoon or None,
                contract_einddatum=contract_einddatum or None, vertrokken_op=vertrokken_op, row_index=row_index,
            ))
        resultaat.sort(key=lambda v: v.vertrokken_op, reverse=True)
        return resultaat

    def get_recent_vertrokken_huurders(self) -> list[VertrokkenHuurder]:
        """Vertrokken huurders die nog binnen de archiveringstermijn vallen
        (_VERTROKKEN_ZICHTBAAR_DAGEN, gerekend vanaf hun contract-einddatum,
        of - als die onbekend/onherkenbaar is - vanaf het moment van
        archiveren) - voor het grijze blokje bovenaan de Huurders-pagina.
        Oudere regels blijven gewoon (permanent) in de sheet staan, zie
        get_alle_vertrokken_huurders()."""
        vandaag = date.today()
        return [
            v for v in self._alle_vertrokken_huurders_ruw()
            if vandaag <= (_parse_contract_einddatum(v.contract_einddatum or "") or v.vertrokken_op)
            + timedelta(days=_VERTROKKEN_ZICHTBAAR_DAGEN)
        ]

    def get_alle_vertrokken_huurders(self) -> list[VertrokkenHuurder]:
        """De volledige, permanente lijst van ooit vertrokken huurders (zie
        "Oude huurders"-pagina) - in tegenstelling tot
        get_recent_vertrokken_huurders() geen tijdsfilter, dus blijft een
        huurder hier voor altijd terug te vinden."""
        return self._alle_vertrokken_huurders_ruw()

    def get_vertrokken_huurder(self, row_index: int) -> VertrokkenHuurder | None:
        """Eén specifieke vertrokken huurder op basis van hun rijnummer in de
        "Vertrokken"-sheet (zie VertrokkenHuurder.row_index) - voor de
        "Oude huurders"-detailpagina."""
        return next((v for v in self._alle_vertrokken_huurders_ruw() if v.row_index == row_index), None)

    def _vertrokken_worksheet(self):
        try:
            return self._spreadsheet.worksheet(self._pand.vertrokken_worksheet)
        except gspread.exceptions.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(
                title=self._pand.vertrokken_worksheet, rows=1000, cols=len(_VERTROKKEN_HEADER)
            )
            ws.append_row(_VERTROKKEN_HEADER, value_input_option="RAW")
            return ws

    @staticmethod
    def _bedrag_of_leeg(bedrag: Decimal | None) -> str:
        return f"{bedrag:.2f}".replace(".", ",") if bedrag is not None else ""

    def _a1(self, row: int, col: int) -> str:
        return gspread.utils.rowcol_to_a1(row, col)
