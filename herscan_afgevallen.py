"""Laat alle huizen die ooit zijn afgevallen opnieuw door alle checks lopen (bijv. na
een bugfix in een van de regels, zoals de 50-meter-vrijstelling bij t/m 3 kamers) en
stuurt er een rapport van. Adressen die je zelf handmatig hebt verwijderd (via de
verwijder-link in het rapport) worden - net als bij handmatig_toevoegen.py
--herprocessen - nooit opnieuw actief.

Gebruik:
    python herscan_afgevallen.py

Leest de bestaande state.json rechtstreeks uit (geen los adressenbestand nodig, in
tegenstelling tot handmatig_toevoegen.py) - elk "afgevallen"-adres staat daar al met
postcode+huisnummer verwerkt in zijn eigen ID.
"""
from __future__ import annotations

import logging
import sys
from datetime import date

from rotterdam_scanner import pipeline, report
from rotterdam_scanner.config import load_config
from rotterdam_scanner.funda_mail import FundaListing
from rotterdam_scanner.handmatig import listing_state_naar_funda_listing
from rotterdam_scanner.mailer import send_report
from rotterdam_scanner.state import StateStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("kamerverhuur_scanner.herscan_afgevallen")


def main() -> int:
    today = date.today()
    try:
        config = load_config()
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1

    state = StateStore(config.state_path)
    afgevallen = [item for item in state.all() if item.status == "afgevallen"]
    listings: list[FundaListing] = []
    onherkend = 0
    for item in afgevallen:
        listing = listing_state_naar_funda_listing(item)
        if listing is None:
            onherkend += 1
            continue
        listings.append(listing)

    if onherkend:
        logger.warning("%d afgevallen adres(sen) hadden een onherkende ID en zijn overgeslagen.", onherkend)
    if not listings:
        logger.info("Geen afgevallen adressen gevonden om opnieuw te checken.")
        return 0

    logger.info("Herscan %d eerder afgevallen adres(sen)...", len(listings))
    result = pipeline.run_handmatig(config, listings, today=today, forceer_herprocessen=True)

    for fout in result.fouten:
        logger.warning(fout)

    subject = (
        f"Kamerverhuur-scanner Rotterdam — herscan afgevallen adressen "
        f"({len(result.nieuw_actief)} alsnog kansrijk, {len(result.alle_actief)} totaal open)"
    )
    html_body = report.build_html_report(result, today, config.gmail_address, config.listing_expiry_days)
    text_body = report.build_text_report(result, today, config.gmail_address)

    try:
        send_report(config, subject, html_body, text_body)
    except Exception:
        logger.exception("Versturen van het rapport is mislukt")
        return 1

    logger.info(
        "Klaar: %d van de %d herscande adressen zijn nu alsnog kansrijk. Rapport verstuurd naar %s.",
        len(result.nieuw_actief),
        len(listings),
        ", ".join(config.report_to),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
