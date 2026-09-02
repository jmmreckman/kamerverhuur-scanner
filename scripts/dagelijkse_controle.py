#!/usr/bin/env python3
"""Draait elk uur (op het hele uur, Europe/Amsterdam) automatisch de
betaalcontrole voor alle panden - zie deploy/docker-compose.yml (service
'dagelijkse-check'; de naam is historisch, dit draait inmiddels elk uur).

Geen losse cron-daemon nodig: dit proces blijft zelf draaien, wacht tot het
volgende hele uur, voert de controle uit voor elk pand uit properties.json,
en begint daarna weer opnieuw te wachten. Eén pand dat faalt (bv. tijdelijk
geen bunq-verbinding) stopt de rest niet - dat pand wordt gewoon het
volgende uur opnieuw geprobeerd. Dit blijft ruim binnen de gratis quota van
zowel de Google Sheets API als bunq - geen reden om dit niet vaker te doen
dan 1x per dag.

De "Nu controleren"-knop op de site blijft daarnaast gewoon werken; dit
script is puur een automatische aanvulling, geen vervanging.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.properties import PropertiesError, load_properties
from kamerverhuur_scanner.runner import run_check

_TIJDZONE = ZoneInfo("Europe/Amsterdam")

logger = logging.getLogger(__name__)


def _seconden_tot_volgende_run(nu: datetime | None = None) -> float:
    """Tijd tot het eerstvolgende hele uur (bv. 14:23 -> 15:00)."""
    nu = nu or datetime.now(_TIJDZONE)
    volgende = nu.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return (volgende - nu).total_seconds()


def _draai_alle_panden(config: Config) -> None:
    try:
        panden = load_properties(config.properties_file)
    except PropertiesError as exc:
        logger.error("Kon panden niet laden: %s", exc)
        return
    for pand in panden:
        try:
            logger.info("[%s] Automatische controle starten...", pand.slug)
            run_check(config, pand, dry_run=False)
        except Exception:
            logger.exception("[%s] Automatische controle mislukt", pand.slug)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    try:
        config = Config.load()
    except ConfigError as exc:
        logger.error("Configuratiefout: %s", exc)
        raise SystemExit(1)

    # Meteen bij opstarten ook een controle uitvoeren (bv. na elke nieuwe
    # deploy) - zo hoeft er nooit tot het volgende hele uur gewacht te worden.
    logger.info("Container gestart - meteen een controle uitvoeren, naast het uurlijkse schema.")
    _draai_alle_panden(config)

    while True:
        wachttijd = _seconden_tot_volgende_run()
        logger.info("Volgende automatische controle over %.0f minuten (op het hele uur).", wachttijd / 60)
        time.sleep(wachttijd)
        _draai_alle_panden(config)


if __name__ == "__main__":
    main()
