#!/usr/bin/env python3
"""Draait main.py elke dag om 09:00 (Europe/Amsterdam) - zie deploy/docker-compose.yml
in de kamerverhuur-scanner-repo (service 'fundazoeker'). Vervangt de Windows
Taakplanner-taak die dit voorheen lokaal triggerde.

Geen losse cron-daemon nodig: dit proces blijft zelf draaien, wacht tot de
volgende 09:00, voert de scan uit, en begint daarna weer opnieuw te wachten.
In tegenstelling tot vergelijkbare scripts elders in dit project (bv. de
uurlijkse betaalcontrole) draait dit BEWUST niet meteen bij het opstarten:
elke scan hier stuurt een echte e-mail naar meerdere mensen, dus een
container-herstart (bv. na een config-wijziging of nieuwe deploy) mag nooit
zomaar een extra rapport versturen.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import main as scanner_main

_TIJDZONE = ZoneInfo("Europe/Amsterdam")
_UUR = 9

logger = logging.getLogger(__name__)


def _seconden_tot_volgende_run(nu: datetime | None = None) -> float:
    """Tijd tot de eerstvolgende 09:00 (bv. 14:23 -> morgen 09:00, 06:10 -> vandaag 09:00)."""
    nu = nu or datetime.now(_TIJDZONE)
    volgende = nu.replace(hour=_UUR, minute=0, second=0, microsecond=0)
    if volgende <= nu:
        volgende += timedelta(days=1)
    return (volgende - nu).total_seconds()


def main() -> None:
    while True:
        wachttijd = _seconden_tot_volgende_run()
        logger.info("Volgende automatische scan over %.1f uur (om 09:00).", wachttijd / 3600)
        time.sleep(wachttijd)
        scanner_main.main()


if __name__ == "__main__":
    main()
