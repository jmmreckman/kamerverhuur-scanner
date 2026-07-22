#!/usr/bin/env python3
"""Legt elke week automatisch een winst-datapunt vast per pand (zie
deploy/docker-compose.yml, service 'winst-snapshot') - zorgt dat de
winst-grafiek op de site blijft aangroeien, ook als niemand de
winstberekeningspagina bezoekt (die legt zelf ook al een datapunt vast bij
elk bezoek, zie webapp/app.py: winstberekening()).

Geen losse cron-daemon nodig: dit proces blijft zelf draaien, wacht 7 dagen,
legt dan voor elk pand een nieuw datapunt vast, en begint weer opnieuw te
wachten. Eén pand dat faalt (bv. tijdelijk geen bunq-verbinding) stopt de
rest niet."""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from decimal import Decimal

from dotenv import load_dotenv

from kamerverhuur_scanner import state
from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.properties import PropertiesError, load_properties
from kamerverhuur_scanner.runner import bereken_winstoverzicht, netto_huurinkomsten_deze_maand
from kamerverhuur_scanner.sheet_client import SheetClient

_INTERVAL_SECONDEN = timedelta(days=7).total_seconds()

logger = logging.getLogger(__name__)


def _leg_snapshot_vast_voor_alle_panden(config: Config) -> None:
    try:
        panden = load_properties(config.properties_file)
    except PropertiesError as exc:
        logger.error("Kon panden niet laden: %s", exc)
        return
    for pand in panden:
        try:
            cache = state.load(pand.slug, config.state_dir)
            if cache:
                sheet = SheetClient(config, pand)
                inkomsten = netto_huurinkomsten_deze_maand(sheet.get_kamers(), cache["resultaten"])
            else:
                inkomsten = Decimal("0")
            overzicht = bereken_winstoverzicht(config, pand, inkomsten)
            state.voeg_winst_snapshot_toe(pand.slug, overzicht.winst, config.state_dir)
            logger.info("[%s] Winst-snapshot vastgelegd: %s.", pand.slug, overzicht.winst)
        except Exception:
            logger.exception("[%s] Winst-snapshot mislukt.", pand.slug)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    try:
        config = Config.load()
    except ConfigError as exc:
        logger.error("Configuratiefout: %s", exc)
        raise SystemExit(1)

    while True:
        logger.info("Winst-snapshot starten voor alle panden...")
        _leg_snapshot_vast_voor_alle_panden(config)
        logger.info("Volgende winst-snapshot over 7 dagen.")
        time.sleep(_INTERVAL_SECONDEN)


if __name__ == "__main__":
    main()
