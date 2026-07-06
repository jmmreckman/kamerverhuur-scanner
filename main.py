#!/usr/bin/env python3
"""Command-line hulpmiddel om de betaalcontrole te testen zonder de website te starten.

De echte controle draait normaal via de "Check betalingen"-knop op de site
(webapp/app.py) - dit script is vooral handig om je bunq/Sheets-koppeling
vanaf de command line te testen.

Gebruik:
    python main.py             # controleert de huur en schrijft sheet + geschiedenis bij
    python main.py --dry-run   # print het resultaat alleen op het scherm, wijzigt niets
"""
from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.runner import run_check


def main() -> int:
    parser = argparse.ArgumentParser(description="Controleert of de huur van alle kamers is binnengekomen.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Toon het resultaat alleen op het scherm; schrijf niets naar de sheet of geschiedenis.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Uitgebreide logging.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    load_dotenv()

    try:
        config = Config.load()
    except ConfigError as exc:
        print(f"Configuratiefout: {exc}", file=sys.stderr)
        return 1

    try:
        _tenants, results, unmatched = run_check(config, dry_run=args.dry_run)
    except Exception as exc:
        logging.getLogger(__name__).error("Huurcontrole mislukt: %s", exc, exc_info=args.verbose)
        return 1

    for r in results:
        print(f"{r.tenant.kamer:>6} | {r.tenant.naam:<25} | {r.status.value:<22} | ontvangen {r.ontvangen_bedrag:.2f}")
    if unmatched:
        print(f"\n{len(unmatched)} niet-gekoppelde inkomende betaling(en):")
        for p in unmatched:
            print(f"  {p.datum:%d-%m-%Y} | {p.tegenpartij_naam} | {p.bedrag:.2f} | {p.omschrijving}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
