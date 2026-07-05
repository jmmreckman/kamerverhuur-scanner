"""Hulpmiddel om de Funda-alertmail-parser te testen tegen een echt voorbeeld.

Gebruik:
  1. Sla een ontvangen Funda-mail (nieuwe-woningen-alert of favorieten-update) op
     als .eml-bestand (in Gmail: rechtsboven op de mail > "Bericht downloaden").
  2. Draai: python tools/test_email_parsing.py pad/naar/alert.eml

Dit toont welke woningen, prijzen en status-updates (onder bod/verkocht) de parser
eruit haalt, zodat je vóór de eerste automatische run kunt checken of de herkenning
klopt. Prijs- en statusherkenning zijn best-effort (ze zoeken tekst in de buurt van
elke woning-link) en dus kwetsbaarder dan de adresherkenning zelf — klopt er iets
niet, pas dan de patronen in rotterdam_scanner/funda_mail.py aan.
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

    if not scan.listings and not scan.status_updates:
        print("Geen funda-woninglinks gevonden in dit bestand.")
        return 1

    if scan.listings:
        print(f"{len(scan.listings)} woning(en) gevonden:\n")
        for listing in scan.listings:
            if listing.adres_bekend:
                print(f"- {listing.straatnaam} {listing.huisnummer}, {listing.woonplaats}")
            else:
                print(f"- (adres niet herkend) {listing.url}")
            prijs_tekst = f"€{listing.prijs:,}".replace(",", ".") if listing.prijs else "(prijs niet herkend)"
            print(f"    object_id={listing.object_id}  prijs={prijs_tekst}  url={listing.url}")

    if scan.status_updates:
        print(f"\n{len(scan.status_updates)} status-update(s) gevonden (bijv. onder bod/verkocht):")
        for object_id, status in scan.status_updates.items():
            print(f"- object_id={object_id}: {status}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Gebruik: python tools/test_email_parsing.py pad/naar/alert.eml")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
