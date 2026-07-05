"""Verwerkt een handmatig aangeleverde lijst adressen (bijv. verzameld door zelf even
door funda.nl te bladeren) en stuurt er direct een rapport-mail van, via dezelfde
checks als de dagelijkse run. De adressen blijven daarna in state.json staan en lopen
dus automatisch mee in alle volgende dagrapporten.

Gebruik:
    python handmatig_toevoegen.py pad/naar/adressen.txt [--herprocessen]

--herprocessen laat ook adressen die al eerder verwerkt zijn opnieuw door alle checks
lopen (geocoding, geo-checks, opkoopbescherming/WOZ, BAG), in plaats van ze over te
slaan. Gebruik dit na een bugfix in een van de checks, om oude foute uitkomsten in
state.json te corrigeren. Handmatig verwijderde adressen worden hierbij nooit
opnieuw actief.

Twee bestandsformaten worden automatisch herkend:

1. Eén adres per regel, "POSTCODE HUISNUMMER[TOEVOEGING] [funda-link]", bijv.:
       3073KJ 47A
       3078CN 44 https://www.funda.nl/detail/koop/rotterdam/huis-vredehagen-44/12345678/
   Regels die met # beginnen of leeg zijn worden overgeslagen.

2. Een ruwe kopieer-plak van een funda-zoekresultatenpagina (selecteer de hele
   resultatenlijst in je browser, kopieer, plak in een tekstbestand) -- adres,
   postcode/plaats, prijs, oppervlaktes, makelaar etc. allemaal op eigen regels.
   Geen scraping: jij bekijkt en kopieert de pagina zelf, dit leest alleen de
   geplakte tekst uit.
"""
from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

from rotterdam_scanner import pipeline, report
from rotterdam_scanner.config import load_config
from rotterdam_scanner.handmatig import parse_bestand
from rotterdam_scanner.mailer import send_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("kamerverhuur_scanner.handmatig")


def main(bestandspad: str, forceer_herprocessen: bool = False) -> int:
    today = date.today()
    tekst = Path(bestandspad).read_text(encoding="utf-8")
    listings, parse_fouten = parse_bestand(tekst)

    for fout in parse_fouten:
        logger.warning(fout)

    if not listings:
        logger.error("Geen enkel adres kon uit '%s' gelezen worden.", bestandspad)
        return 1

    try:
        config = load_config()
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1

    logger.info("Verwerk %d handmatig aangeleverd adres(sen)...", len(listings))
    result = pipeline.run_handmatig(config, listings, today=today, forceer_herprocessen=forceer_herprocessen)
    result.fouten = parse_fouten + result.fouten

    for fout in result.fouten:
        logger.warning(fout)

    subject = (
        f"Kamerverhuur-scanner Rotterdam — handmatige toevoeging "
        f"({len(listings)} adres(sen) verwerkt, {len(result.alle_actief)} totaal open)"
    )
    html_body = report.build_html_report(result, today, config.gmail_address, config.listing_expiry_days)
    text_body = report.build_text_report(result, today, config.gmail_address)

    try:
        send_report(config, subject, html_body, text_body)
    except Exception:
        logger.exception("Versturen van het rapport is mislukt")
        return 1

    logger.info(
        "Klaar: %d nieuw actief, %d nieuw afgevallen, %d onbekend adres. Rapport verstuurd naar %s.",
        len(result.nieuw_actief),
        len(result.nieuw_afgevallen),
        len(result.nieuw_onbekend_adres),
        ", ".join(config.report_to),
    )
    return 0


if __name__ == "__main__":
    argumenten = sys.argv[1:]
    forceer_herprocessen = "--herprocessen" in argumenten
    bestandspaden = [a for a in argumenten if a != "--herprocessen"]

    if len(bestandspaden) != 1:
        print("Gebruik: python handmatig_toevoegen.py pad/naar/adressen.txt [--herprocessen]")
        sys.exit(1)
    sys.exit(main(bestandspaden[0], forceer_herprocessen))
