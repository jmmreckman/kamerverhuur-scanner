"""Lezen en terugschrijven van de kamers/huurdersgegevens in Google Sheets.

Verwachte kolomindeling op het hoofdtabblad (rij 1 = koprij, data vanaf rij 2):

    A Naam | B Kamer | C Verwacht bedrag | D IBAN (optioneel) |
    E Zoekwoord (optioneel) | F Status | G Ontvangen bedrag | H Laatst gecontroleerd

Een rij met een lege naam maar een ingevulde kamer betekent: kamer staat leeg.

Daarnaast is er een "Historie" tabblad (wordt aangemaakt als het nog niet bestaat)
met kolommen: Datum | Kamer | Huurder | Verwacht | Ontvangen | Status - elke
uitgevoerde controle voegt hier een rij per kamer aan toe.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import gspread

from .config import Config
from .models import HistorieRegel, Status, Tenant, TenantResult
from .utils import parse_bedrag

COL_NAAM = 1
COL_KAMER = 2
COL_VERWACHT = 3
COL_IBAN = 4
COL_ZOEKWOORD = 5
COL_STATUS = 6
COL_ONTVANGEN = 7
COL_LAATST_GECONTROLEERD = 8

HEADER_ROW = 1

_HISTORIE_HEADER = ["Datum", "Kamer", "Huurder", "Verwacht bedrag", "Ontvangen bedrag", "Status"]


class SheetClient:
    def __init__(self, config: Config):
        self._config = config
        gc = gspread.service_account(filename=config.google_service_account_file)
        self._spreadsheet = gc.open_by_key(config.google_sheet_id)
        self._worksheet = self._spreadsheet.worksheet(config.google_sheet_worksheet)

    def get_kamers(self) -> list[Tenant]:
        """Geeft alle kamers terug, inclusief leegstaande (lege naam, wel een kamernummer)."""
        rows = self._worksheet.get_all_values()
        kamers: list[Tenant] = []
        for offset, row in enumerate(rows[HEADER_ROW:]):
            row_index = HEADER_ROW + 1 + offset
            row = row + [""] * (COL_LAATST_GECONTROLEERD - len(row))
            kamer = row[COL_KAMER - 1].strip()
            if not kamer:
                continue  # lege rij overslaan
            kamers.append(
                Tenant(
                    row_index=row_index,
                    naam=row[COL_NAAM - 1].strip(),
                    kamer=kamer,
                    verwacht_bedrag=parse_bedrag(row[COL_VERWACHT - 1]),
                    iban=(row[COL_IBAN - 1].strip().replace(" ", "").upper() or None),
                    zoekwoord=(row[COL_ZOEKWOORD - 1].strip() or None),
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
    ) -> None:
        updates = [
            {"range": self._a1(row_index, COL_NAAM), "values": [[naam]]},
            {"range": self._a1(row_index, COL_KAMER), "values": [[kamer]]},
            {
                "range": self._a1(row_index, COL_VERWACHT),
                "values": [[f"{verwacht_bedrag:.2f}".replace(".", ",")]],
            },
            {"range": self._a1(row_index, COL_IBAN), "values": [[iban or ""]]},
            {"range": self._a1(row_index, COL_ZOEKWOORD), "values": [[zoekwoord or ""]]},
        ]
        self._worksheet.batch_update(updates, value_input_option="USER_ENTERED")

    def add_kamer(
        self,
        naam: str,
        kamer: str,
        verwacht_bedrag: Decimal,
        iban: str | None,
        zoekwoord: str | None,
    ) -> None:
        row = [naam, kamer, f"{verwacht_bedrag:.2f}".replace(".", ","), iban or "", zoekwoord or "", "", "", ""]
        self._worksheet.append_row(row, value_input_option="USER_ENTERED")

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

    def append_history(self, results: list[TenantResult], vandaag: date) -> None:
        ws = self._history_worksheet()
        rows = [
            [
                vandaag.strftime("%d-%m-%Y"),
                r.tenant.kamer,
                r.tenant.naam,
                f"{r.tenant.verwacht_bedrag:.2f}".replace(".", ","),
                f"{r.ontvangen_bedrag:.2f}".replace(".", ","),
                r.status.value,
            ]
            for r in results
        ]
        if rows:
            ws.append_rows(rows, value_input_option="USER_ENTERED")

    def get_geschiedenis(self, kamer: str) -> list[HistorieRegel]:
        ws = self._history_worksheet()
        rows = ws.get_all_values()[1:]  # koprij overslaan
        regels: list[HistorieRegel] = []
        for row in rows:
            row = row + [""] * (6 - len(row))
            if row[1].strip() != kamer:
                continue
            regels.append(
                HistorieRegel(
                    datum=datetime.strptime(row[0].strip(), "%d-%m-%Y").date(),
                    kamer=row[1].strip(),
                    huurder=row[2].strip(),
                    verwacht_bedrag=parse_bedrag(row[3]),
                    ontvangen_bedrag=parse_bedrag(row[4]),
                    status=Status(row[5].strip()),
                )
            )
        regels.sort(key=lambda r: r.datum)
        return regels

    def _history_worksheet(self):
        try:
            return self._spreadsheet.worksheet(self._config.history_worksheet)
        except gspread.exceptions.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(
                title=self._config.history_worksheet, rows=1000, cols=len(_HISTORIE_HEADER)
            )
            ws.append_row(_HISTORIE_HEADER, value_input_option="USER_ENTERED")
            return ws

    def _a1(self, row: int, col: int) -> str:
        return gspread.utils.rowcol_to_a1(row, col)
