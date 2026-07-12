"""Zelfde Excel-import als import_excel.py, maar stuurt de data over het
netwerk naar een draaiende instantie van de app (bijv. op een VPS) in
plaats van rechtstreeks in een lokale database te schrijven. Handig om de
historie in één keer over te zetten naar een publieke deploy.

Gebruik:
    python import_excel_remote.py "C:\\pad\\naar\\gewicht.xlsx" https://gewicht.steenhub.nl gebruikersnaam wachtwoord
"""
import base64
import json
import ssl
import sys
import urllib.error
import urllib.request

import certifi
import openpyxl

from import_excel import parse_date, parse_weight

BATCH_SIZE = 500

# Gebruik certifi's eigen, actuele lijst met vertrouwde certificaten in
# plaats van die van het besturingssysteem - voorkomt "certificate has
# expired"-fouten op Windows-machines met een verouderde certificatenlijst.
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def send_batch(base_url: str, auth_header: str, batch: list[tuple]) -> None:
    body = json.dumps(
        {"entries": [{"date": d.isoformat(), "weight": w} for d, w in batch]}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/weight/bulk",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": auth_header},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, context=SSL_CONTEXT)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Fout van de server ({e.code}): {e.read().decode('utf-8', 'replace')}")


def main(path: str, base_url: str, username: str, password: str) -> None:
    wb = openpyxl.load_workbook(path, data_only=True)
    sheet = wb.active

    auth_header = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()

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

    for i in range(0, len(entries), BATCH_SIZE):
        batch = entries[i : i + BATCH_SIZE]
        send_batch(base_url, auth_header, batch)
        print(f"...{min(i + BATCH_SIZE, len(entries))}/{len(entries)} verstuurd")

    print(f"Klaar: {len(entries)} metingen verstuurd naar {base_url}, {skipped} rijen overgeslagen (bijv. header).")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "Gebruik: python import_excel_remote.py <excel-pad> <https://url-van-de-app> "
            "<gebruikersnaam> <wachtwoord>"
        )
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
