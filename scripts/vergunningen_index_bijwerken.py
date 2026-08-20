#!/usr/bin/env python3
"""Bouwt en onderhoudt de volledige index van Rotterdamse kamerverhuurvergunningen
voor de kaart-website (de "Toon vergunningen"-laag + het data-analyse-dashboard,
zie rotterdam_scanner/vergunningenindex.py en kansen_site/app.py).

Draait als eigen container-service (zie deploy/docker-compose.yml, service
'vergunningen-index'). Werkt zelf-plannend: zolang de eenmalige backfill van het
archief nog loopt haalt hij elke paar minuten een begrensde batch bekendmakingen
op (ophalen + parsen + geocoderen); zodra het archief compleet is schakelt hij over
naar één lichte bijwerk-run per dag (alleen nieuwe vergunningen). Start meteen bij
het opstarten - deze index stuurt niemand een mail, dus een herstart is onschadelijk.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from rotterdam_scanner import vergunningenindex
from rotterdam_scanner.config import load_config

_TIJDZONE = ZoneInfo("Europe/Amsterdam")
_UUR = 7  # dagelijkse bijwerking (na de nachtelijke publicaties, vóór de 09:00-scan)
_BACKFILL_PAUZE_SECONDEN = 180  # rustig doorbouwen tijdens de eenmalige backfill
_BATCH = 150  # bekendmakingen per run (ophalen + parsen + geocoderen)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("kamerverhuur_scanner.vergunningen_index")


def _index_pad(config) -> Path:
    return Path(config.state_path).parent / "vergunningen_index.json"


def _seconden_tot_volgende_dag(nu: datetime | None = None) -> float:
    nu = nu or datetime.now(_TIJDZONE)
    volgende = nu.replace(hour=_UUR, minute=0, second=0, microsecond=0)
    if volgende <= nu:
        volgende += timedelta(days=1)
    return (volgende - nu).total_seconds()


def main() -> None:
    while True:
        config = load_config()
        try:
            voortgang = vergunningenindex.werk_bij(_index_pad(config), batch=_BATCH)
        except Exception:  # noqa: BLE001 - nooit de daemon laten crashen op een storing
            logger.exception("Bijwerken van de vergunningen-index is mislukt")
            time.sleep(_BACKFILL_PAUZE_SECONDEN)
            continue

        logger.info(
            "Vergunningen-index: %d totaal, %d bruikbaar, %d verwerkt deze run, %d resterend.",
            voortgang["totaal"], voortgang["bruikbaar"],
            voortgang["verwerkt_deze_run"], voortgang["resterend"],
        )

        if voortgang["compleet"]:
            wachttijd = _seconden_tot_volgende_dag()
            logger.info("Archief compleet - volgende bijwerking over %.1f uur.", wachttijd / 3600)
            time.sleep(wachttijd)
        else:
            time.sleep(_BACKFILL_PAUZE_SECONDEN)


if __name__ == "__main__":
    main()
