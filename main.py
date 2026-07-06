#!/usr/bin/env python3
"""Command-line entrypoint voor de kamerverhuur-scanner.

Gebruik:
    python main.py             # controleert de huur, schrijft de sheet bij en mailt het rapport
    python main.py --dry-run   # print het rapport alleen op het scherm, wijzigt niets
"""
from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.runner import run


def main() -> int:
    parser = argparse.ArgumentParser(description="Controleert of de huur van alle huurders is binnengekomen.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Toon het rapport alleen op het scherm; verstuur geen e-mail en schrijf niets naar de sheet.",
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
        run(config, dry_run=args.dry_run)
    except Exception as exc:  # bovenste laag: nette foutmelding i.p.v. crash in een cronjob
        logging.getLogger(__name__).error("Huurcontrole mislukt: %s", exc, exc_info=args.verbose)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
