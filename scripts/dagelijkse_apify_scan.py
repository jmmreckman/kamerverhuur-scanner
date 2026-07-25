#!/usr/bin/env python3
"""Draait elke dag om 08:00 (Europe/Amsterdam) de kleine, dagelijkse
Apify-scan (pipeline.run_apify(), zie README voor de kostenafweging tussen
deze dagelijkse "alleen de nieuwste woningen"-pull en de grote wekelijkse
volledige pull in wekelijkse_apify_scan.py).

Update alleen state.json - stuurt zelf GEEN mailrapport (dat blijft
main.py/dagelijkse_scan.py, gebaseerd op de mail-alert). Nieuwe/gewijzigde
kansen zijn meteen zichtbaar op kansen.steenhub.nl, of via de "Ververs
nu"-knop daar. Sla je APIFY_API_TOKEN nog niet in fundazoeker.env in, of
staan er nog geen zoek-URL's (env APIFY_SEARCH_URLS, of toegevoegd via de
"Zoekopdrachten"-pagina op kansen.steenhub.nl), dan slaat dit script
zichzelf netjes over (geen crash, geen restart-loop) tot je dat wel doet."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from rotterdam_scanner import apify_scraper, pipeline, zoek_urls
from rotterdam_scanner.config import load_config

_TIJDZONE = ZoneInfo("Europe/Amsterdam")
_UUR = 8

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("kamerverhuur_scanner.dagelijkse_apify_scan")


def _seconden_tot_volgende_run(nu: datetime | None = None) -> float:
    nu = nu or datetime.now(_TIJDZONE)
    volgende = nu.replace(hour=_UUR, minute=0, second=0, microsecond=0)
    if volgende <= nu:
        volgende += timedelta(days=1)
    return (volgende - nu).total_seconds()


def main() -> None:
    while True:
        wachttijd = _seconden_tot_volgende_run()
        logger.info("Volgende dagelijkse Apify-scan over %.1f uur (om 08:00).", wachttijd / 3600)
        time.sleep(wachttijd)

        config = load_config()
        if not apify_scraper.is_ingesteld(config, zoek_urls.laad(config)):
            logger.info(
                "APIFY_API_TOKEN en/of de zoek-URL's zijn nog niet ingesteld - "
                "dagelijkse Apify-scan overgeslagen."
            )
            continue

        result = pipeline.run_apify(config)
        for fout in result.fouten:
            logger.warning(fout)
        logger.info(
            "Dagelijkse Apify-scan klaar: %d nieuw actief, %d afgevallen, %d totaal open.",
            len(result.nieuw_actief), len(result.nieuw_afgevallen), len(result.alle_actief),
        )


if __name__ == "__main__":
    main()
