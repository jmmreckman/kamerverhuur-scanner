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
      ontvangen" wordt gezien

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
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

import gspread

from .config import Config
from .models import Aanmelding, HistorieRegel, Pand, Payment, Status, Tenant, TenantResult
from .utils import parse_bedrag

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

HEADER_ROW = 1
_SOMRIJ_LABELS = {"totalen", "totaal"}

_HISTORIE_HEADER = ["Maand", "Kamer", "Huurder", "Verwacht bedrag", "Ontvangen bedrag", "Status", "Betaaldatum"]
_MAAND_PATROON = re.compile(r"\d{4}-\d{2}")

_AANMELDINGEN_HEADER = [
    "Datum", "Kamer", "Naam", "Email", "Telefoon", "Huidig adres", "Studie",
    "Studentnummer", "Gewenste ingangsdatum", "Gewenste huurduur",
    "Inkomstenbron", "Inkomsten (bedrag)", "Borgsteller", "Bezichtiging",
    "Video-bel nummer", "Bewijs inschrijving",
]


def _optioneel(waarde: str) -> str | None:
    return waarde.strip() or None


def _naar_ja_nee(waarde: bool) -> str:
    return "JA" if waarde else "NEE"


def _naar_bool(waarde: str) -> bool:
    return waarde.strip().upper() in {"JA", "TRUE", "WAAR", "1"}


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
            row = row + [""] * (COL_BORG - len(row))
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

    def add_kamer(
        self,
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
        row = [
            kamer,
            naam,
            self._bedrag_of_leeg(kale_huurprijs),
            self._bedrag_of_leeg(servicekosten),
            f"{verwacht_bedrag:.2f}".replace(".", ","),
            contract_einddatum or "",
            opmerking or "",
            iban or "",
            zoekwoord or "",
            "",
            "",
            "",
            "",
            "",
            "",
            email or "",
            telefoonnummer or "",
            geboortedatum or "",
            geboorteplaats or "",
            studentnummer or "",
            studierichting or "",
            borgsteller_naam or "",
            borgsteller_relatie or "",
            contract_startdatum or "",
            self._bedrag_of_leeg(borg_bedrag),
        ]
        self._worksheet.append_row(row, value_input_option="USER_ENTERED")

    def update_aanbod(self, row_index: int, beschikbaar: bool, omschrijving: str | None, map_id: str | None) -> None:
        updates = [
            {"range": self._a1(row_index, COL_BESCHIKBAAR), "values": [[_naar_ja_nee(beschikbaar)]]},
            {"range": self._a1(row_index, COL_ADVERTENTIE_OMSCHRIJVING), "values": [[omschrijving or ""]]},
            {"range": self._a1(row_index, COL_ADVERTENTIE_MAP_ID), "values": [[map_id or ""]]},
        ]
        self._worksheet.batch_update(updates, value_input_option="USER_ENTERED")

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
        controleren binnen dezelfde maand."""
        ws = self._history_worksheet()
        bestaande = ws.get_all_values()
        # Sleutel op (kamer, maand) samen - alleen op kamer sleutelen liet bij
        # meerdere bestaande maanden voor dezelfde kamer alleen de laatst
        # geziene rij over, waardoor eerdere maanden niet meer gevonden
        # werden en er per ongeluk dubbele regels bijkwamen.
        rij_voor_kamer_maand = {
            (row[1].strip(), row[0].strip()): i
            for i, row in enumerate(bestaande[1:], start=2)
            if len(row) > 1
        }

        updates = []
        nieuwe_rijen = []
        for r in results:
            betaaldatum = _laatste_betaaldatum(r.gematchte_betalingen)
            rij = [
                maand,
                r.tenant.kamer,
                r.tenant.naam,
                f"{r.tenant.verwacht_bedrag:.2f}".replace(".", ","),
                f"{r.ontvangen_bedrag:.2f}".replace(".", ","),
                r.status.value,
                betaaldatum.strftime("%d-%m-%Y") if betaaldatum else "",
            ]
            rij_index = rij_voor_kamer_maand.get((r.tenant.kamer, maand))
            if rij_index:
                updates.append({"range": f"A{rij_index}:G{rij_index}", "values": [rij]})
            else:
                nieuwe_rijen.append(rij)

        if updates:
            ws.batch_update(updates, value_input_option="USER_ENTERED")
        if nieuwe_rijen:
            ws.append_rows(nieuwe_rijen, value_input_option="USER_ENTERED")

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
            row for row in data_rows
            if not (
                len(row) > 2 and row[1].strip() == kamer and row[2].strip() == huurder
                and row[0].strip() < oudste_geldige_maand
            )
        ]
        verwijderd = len(data_rows) - len(schoon)
        if verwijderd > 0:
            ws.clear()
            ws.append_row(header, value_input_option="USER_ENTERED")
            if schoon:
                ws.append_rows(schoon, value_input_option="USER_ENTERED")
        return verwijderd

    def dedupliceer_geschiedenis(self) -> int:
        """Verwijdert dubbele Historie-regels voor dezelfde (kamer, maand) -
        combinatie (kon ontstaan door een bug in upsert_history) en houdt de
        ONDERSTE (dus laatst weggeschreven, meest recente) regel. Geeft het
        aantal verwijderde regels terug."""
        ws = self._history_worksheet()
        rows = ws.get_all_values()
        if len(rows) <= 1:
            return 0
        header, data_rows = rows[0], rows[1:]

        laatste_per_sleutel: dict[tuple[str, str], list[str]] = {}
        volgorde: list[tuple[str, str]] = []
        for row in data_rows:
            row = row + [""] * (7 - len(row))
            sleutel = (row[1].strip(), row[0].strip())
            if sleutel not in laatste_per_sleutel:
                volgorde.append(sleutel)
            laatste_per_sleutel[sleutel] = row  # overschrijft met de laatst geziene (= onderste) rij

        schoon = [laatste_per_sleutel[sleutel] for sleutel in volgorde]
        verwijderd = len(data_rows) - len(schoon)
        if verwijderd > 0:
            ws.clear()
            ws.append_row(header, value_input_option="USER_ENTERED")
            if schoon:
                ws.append_rows(schoon, value_input_option="USER_ENTERED")
        return verwijderd

    def get_geschiedenis(self, kamer: str) -> list[HistorieRegel]:
        ws = self._history_worksheet()
        rows = ws.get_all_values()[1:]  # koprij overslaan
        regels: list[HistorieRegel] = []
        for row in rows:
            row = row + [""] * (7 - len(row))
            if row[1].strip() != kamer or not _MAAND_PATROON.fullmatch(row[0].strip()):
                continue  # andere kamer, of een regel van vóór deze indeling (oud datumformaat)
            try:
                regels.append(
                    HistorieRegel(
                        maand=row[0].strip(),
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
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")

    def get_aanmeldingen(self) -> list[list[str]]:
        ws = self._aanmeldingen_worksheet()
        rows = ws.get_all_values()[1:]  # koprij overslaan
        return [row for row in rows if any(cel.strip() for cel in row)]

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

    @staticmethod
    def _bedrag_of_leeg(bedrag: Decimal | None) -> str:
        return f"{bedrag:.2f}".replace(".", ",") if bedrag is not None else ""

    def _a1(self, row: int, col: int) -> str:
        return gspread.utils.rowcol_to_a1(row, col)
