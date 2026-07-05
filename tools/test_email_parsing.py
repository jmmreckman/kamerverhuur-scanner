"""Hulpmiddel om de Funda-alertmail-parser te testen tegen een echt voorbeeld.

Gebruik:
  1. Sla een ontvangen Funda-alertmail op als .eml-bestand (in Gmail: rechtsboven
     op de mail > "Bericht downloaden").
  2. Draai: python tools/test_email_parsing.py pad/naar/alert.eml

Dit toont welke woningen en prijzen de parser eruit haalt, zodat je vóór de eerste
automatische run kunt checken of de herkenning klopt. Adres/postcode/prijs worden uit
de zichtbare tekst rond elke woning-link gehaald (funda's links zijn zelf ondoorzichtige
clicktracking-URL's zonder bruikbare informatie) — kwetsbaarder dan een simpele
URL-parse, dus klopt er iets niet, pas dan de patronen in
rotterdam_scanner/funda_mail.py aan.
"""
from __future__ import annotations

import email
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rotterdam_scanner.funda_mail import _get_body, scan_email_body  # noqa: E402


def main(eml_path: str) -> int:
    raw = Path(eml_path).read_bytes()
    msg = email.message_from_bytes(raw)
    body = _get_body(msg)
    scan = scan_email_body(body)

    if not scan.listings:
        print("Geen funda-woninglinks gevonden in dit bestand.")
    else:
        print(f"{len(scan.listings)} woning(en) gevonden:\n")
        for listing in scan.listings:
            if listing.adres_bekend:
                print(f"- {listing.weergavenaam}")
            else:
                print(f"- (adres niet herkend) {listing.url}")
            prijs_tekst = f"€{listing.prijs:,}".replace(",", ".") if listing.prijs else "(prijs niet herkend)"
            print(f"    object_id={listing.object_id}  prijs={prijs_tekst}")
            print(f"    url={listing.url}")

    if scan.waarschuwingen:
        print("\nWaarschuwingen:")
        for w in scan.waarschuwingen:
            print(f"- {w}")

    return 0 if scan.listings else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Gebruik: python tools/test_email_parsing.py pad/naar/alert.eml")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
