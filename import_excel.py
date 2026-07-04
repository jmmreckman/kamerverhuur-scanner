"""Eenmalige import van je bestaande gewicht-Excel.

Verwacht formaat: kolom A = datum, kolom B = gewicht (getal, evt. met komma
als decimaalteken als het als tekst is opgeslagen). Header-rij wordt
automatisch overgeslagen als kolom A geen geldige datum bevat.

Gebruik:
    python import_excel.py "C:\\pad\\naar\\gewicht.xlsx"
"""
import sys
from datetime import date, datetime

import openpyxl

import db


def parse_weight(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def main(path: str) -> None:
    wb = openpyxl.load_workbook(path, data_only=True)
    sheet = wb.active

    db.init_db()
    entries = []
    skipped = 0

    for row in sheet.iter_rows(min_row=1, max_col=2, values_only=True):
        raw_date, raw_weight = row[0], row[1]
        entry_date = parse_date(raw_date)
        weight = parse_weight(raw_weight)
        if entry_date is None or weight is None:
            skipped += 1
            continue
        entries.append((entry_date, weight))

    db.bulk_upsert_manual_weights(entries)
    print(f"Klaar: {len(entries)} metingen geimporteerd, {skipped} rijen overgeslagen (bijv. header).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Gebruik: python import_excel.py <pad-naar-excel-bestand>")
        sys.exit(1)
    main(sys.argv[1])
