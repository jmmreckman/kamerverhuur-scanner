#!/usr/bin/env python3
"""Draait elke maandag om 07:00 (Europe/Amsterdam) de grote, volledige
Apify-scan (pipeline.run_apify_volledig()): haalt het complete actieve
Funda-aanbod op i.p.v. alleen de nieuwste woningen. Dient twee doelen:
de inhaalslag voor woningen die de kleinere dagelijkse scans gemist hebben,
en automatische verkocht/introkken-detectie (zie pipeline.py voor de
2-weken-op-rij-regel).

Update alleen state.json - stuurt zelf geen mailrapport. Sla je
APIFY_API_TOKEN nog niet in fundazoeker.env in, of staan er nog geen
zoek-URL's (env APIFY_SEARCH_URLS, of toegevoegd via de
"Zoekopdrachten"-pagina op kansen.steenhub.nl), dan slaat dit script
zichzelf netjes over (geen crash, geen restart-loop)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from rotterdam_scanner import apify_scraper, pipeline, zoek_urls
from rotterdam_scanner.config import load_config

_TIJDZONE = ZoneInfo("Europe/Amsterdam")
_WEEKDAG = 0  # maandag (datetime.weekday(): maandag = 0 .. zondag = 6)
_UUR = 7

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("kamerverhuur_scanner.wekelijkse_apify_scan")


def _seconden_tot_volgende_run(nu: datetime | None = None) -> float:
    nu = nu or datetime.now(_TIJDZONE)
    dagen_tot_maandag = (_WEEKDAG - nu.weekday()) % 7
    volgende = (nu + timedelta(days=dagen_tot_maandag)).replace(hour=_UUR, minute=0, second=0, microsecond=0)
    if volgende <= nu:
        volgende += timedelta(days=7)
    return (volgende - nu).total_seconds()


def main() -> None:
    while True:
        wachttijd = _seconden_tot_volgende_run()
        logger.info("Volgende wekelijkse volledige Apify-scan over %.1f uur (maandag 07:00).", wachttijd / 3600)
        time.sleep(wachttijd)

        config = load_config()
        if not apify_scraper.is_ingesteld(config, zoek_urls.laad(config)):
            logger.info(
                "APIFY_API_TOKEN en/of de zoek-URL's zijn nog niet ingesteld - "
                "wekelijkse volledige Apify-scan overgeslagen."
            )
            continue

        result = pipeline.run_apify_volledig(config)
        for fout in result.fouten:
            logger.warning(fout)
        logger.info(
            "Wekelijkse volledige Apify-scan klaar: %d nieuw actief, %d afgevallen "
            "(incl. vermoedelijk verkocht), %d totaal open.",
            len(result.nieuw_actief), len(result.nieuw_afgevallen), len(result.alle_actief),
        )


if __name__ == "__main__":
    main()
