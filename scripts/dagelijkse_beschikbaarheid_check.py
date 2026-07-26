#!/usr/bin/env python3
"""Draait elke dag om 08:00 (Europe/Amsterdam) de gratis beschikbaarheid-check
(pipeline.run_beschikbaarheidscheck(), zie README): bezoekt voor elke "actief"
woning de eigen Funda-pagina en zet 'm op "afgevallen" zodra die "verkocht"
blijkt. Vervangt de eerdere (betaalde, en in de praktijk onbetrouwbare)
Apify-scans.

Update alleen state.json - stuurt zelf GEEN mailrapport (dat blijft
main.py/dagelijkse_scan.py, gebaseerd op de mail-alert). Wijzigingen zijn
meteen zichtbaar op kansen.steenhub.nl."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from rotterdam_scanner import pipeline
from rotterdam_scanner.config import load_config

_TIJDZONE = ZoneInfo("Europe/Amsterdam")
_UUR = 8

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("kamerverhuur_scanner.dagelijkse_beschikbaarheid_check")


def _seconden_tot_volgende_run(nu: datetime | None = None) -> float:
    nu = nu or datetime.now(_TIJDZONE)
    volgende = nu.replace(hour=_UUR, minute=0, second=0, microsecond=0)
    if volgende <= nu:
        volgende += timedelta(days=1)
    return (volgende - nu).total_seconds()


def main() -> None:
    while True:
        wachttijd = _seconden_tot_volgende_run()
        logger.info("Volgende beschikbaarheid-check over %.1f uur (om 08:00).", wachttijd / 3600)
        time.sleep(wachttijd)

        config = load_config()
        result = pipeline.run_beschikbaarheidscheck(config)
        for fout in result.fouten:
            logger.warning(fout)
        logger.info(
            "Beschikbaarheid-check klaar: %d niet meer beschikbaar, %d totaal nog open.",
            len(result.nieuw_afgevallen), len(result.alle_actief),
        )


if __name__ == "__main__":
    main()
