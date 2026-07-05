"""Hulpmiddel om de Funda-alertmail-parser te testen tegen een echt voorbeeld.

Gebruik:
  1. Sla een ontvangen Funda-alertmail op als .eml-bestand (in Gmail: rechtsboven
     op de mail > "Bericht downloaden").
  2. Draai: python tools/test_email_parsing.py pad/naar/alert.eml

Dit toont welke woningen de parser eruit haalt, zodat je vóór de eerste
automatische run kunt checken of de herkenning klopt.
"""
from __future__ import annotations

import email
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rotterdam_scanner.funda_mail import _get_body, extract_listings_from_email_body  # noqa: E402


def main(eml_path: str) -> int:
    raw = Path(eml_path).read_bytes()
    msg = email.message_from_bytes(raw)
    body = _get_body(msg)
    listings = extract_listings_from_email_body(body)

    if not listings:
        print("Geen funda-woninglinks gevonden in dit bestand.")
        return 1

    print(f"{len(listings)} woning(en) gevonden:\n")
    for listing in listings:
        if listing.adres_bekend:
            print(f"- {listing.straatnaam} {listing.huisnummer}, {listing.woonplaats}")
        else:
            print(f"- (adres niet herkend) {listing.url}")
        print(f"    object_id={listing.object_id}  url={listing.url}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Gebruik: python tools/test_email_parsing.py pad/naar/alert.eml")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
