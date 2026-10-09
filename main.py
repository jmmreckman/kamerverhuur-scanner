#!/usr/bin/env python3
"""Command-line hulpmiddel om de betaalcontrole te testen zonder de website te starten.

De echte controle draait normaal via de "Check betalingen"-knop op de site
(webapp/app.py) - dit script is vooral handig om je bunq/Sheets-koppeling
vanaf de command line te testen.

Gebruik:
    python main.py <pand-slug>             # controleert de huur en schrijft sheet + geschiedenis bij
    python main.py <pand-slug> --dry-run   # print het resultaat alleen op het scherm, wijzigt niets
    python main.py --lijst                 # toont alle beschikbare pand-slugs uit properties.json
"""
from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.properties import PropertiesError, find_pand, load_properties
from kamerverhuur_scanner.runner import run_check


def main() -> int:
    parser = argparse.ArgumentParser(description="Controleert of de huur van alle kamers van een pand is binnengekomen.")
    parser.add_argument("pand_slug", nargs="?", help="De 'slug' van het pand uit properties.json, bv. mahoniestraat")
    parser.add_argument("--lijst", action="store_true", help="Toon alle beschikbare pand-slugs en stop.")
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
        properties = load_properties(config.properties_file)
    except (ConfigError, PropertiesError) as exc:
        print(f"Configuratiefout: {exc}", file=sys.stderr)
        return 1

    if args.lijst or not args.pand_slug:
        print("Beschikbare panden:")
        for pand in properties:
            print(f"  {pand.slug} - {pand.naam}")
        return 0 if args.lijst else 1

    pand = find_pand(properties, args.pand_slug)
    if pand is None:
        print(f"Pand '{args.pand_slug}' niet gevonden. Gebruik --lijst om beschikbare panden te zien.", file=sys.stderr)
        return 1

    try:
        _tenants, results, unmatched = run_check(config, pand, dry_run=args.dry_run)
    except Exception as exc:
        logging.getLogger(__name__).error("Huurcontrole mislukt: %s", exc, exc_info=args.verbose)
        return 1

    print(f"--- {pand.naam} ---")
    for r in results:
        print(f"{r.tenant.kamer:>6} | {r.tenant.naam:<25} | {r.status.value:<22} | ontvangen {r.ontvangen_bedrag:.2f}")
    if unmatched:
        print(f"\n{len(unmatched)} niet-gekoppelde inkomende betaling(en):")
        for p in unmatched:
            print(f"  {p.datum:%d-%m-%Y} | {p.tegenpartij_naam} | {p.bedrag:.2f} | {p.omschrijving}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
