"""Lezen en terugschrijven van de huurdersgegevens in Google Sheets.

Verwachte kolomindeling op het tabblad (rij 1 = koprij, data vanaf rij 2):

    A Naam | B Kamer | C Verwacht bedrag | D IBAN (optioneel) |
    E Zoekwoord (optioneel) | F Status | G Ontvangen bedrag | H Laatst gecontroleerd
"""
from __future__ import annotations

from datetime import datetime

import gspread

from .config import Config
from .models import Tenant, TenantResult
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
FIRST_DATA_ROW = 2


class SheetClient:
    def __init__(self, config: Config):
        self._config = config
        gc = gspread.service_account(filename=config.google_service_account_file)
        spreadsheet = gc.open_by_key(config.google_sheet_id)
        self._worksheet = spreadsheet.worksheet(config.google_sheet_worksheet)

    def get_tenants(self) -> list[Tenant]:
        rows = self._worksheet.get_all_values()
        tenants: list[Tenant] = []
        for offset, row in enumerate(rows[HEADER_ROW:]):
            row_index = HEADER_ROW + 1 + offset
            row = row + [""] * (COL_LAATST_GECONTROLEERD - len(row))
            naam = row[COL_NAAM - 1].strip()
            if not naam:
                continue  # lege rij overslaan
            tenants.append(
                Tenant(
                    row_index=row_index,
                    naam=naam,
                    kamer=row[COL_KAMER - 1].strip(),
                    verwacht_bedrag=parse_bedrag(row[COL_VERWACHT - 1]),
                    iban=(row[COL_IBAN - 1].strip().replace(" ", "").upper() or None),
                    zoekwoord=(row[COL_ZOEKWOORD - 1].strip() or None),
                )
            )
        return tenants

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

    def _a1(self, row: int, col: int) -> str:
        return gspread.utils.rowcol_to_a1(row, col)
