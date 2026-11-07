#!/usr/bin/env python3
"""Evohome-spike/login: controleert de Total Connect Comfort-inloggegevens en
leest de structuur (huizen -> kamers/zones) uit, zodat we de evohome-client op
de echte data kunnen bouwen. Gebruikt de onderhouden library `evohome-async`
(dezelfde die Home Assistant gebruikt), die de verschuivende Honeywell/Resideo-
login voor ons afhandelt.

Let op: evohome-async 2.x/3.x vereist Python 3.13; onze image draait 3.12, dus
we gebruiken 1.0.6 (nieuwste 3.12-compatibele versie) - zelfde API-vorm.

Zet in app.env op de VPS: EVOHOME_USERNAME + EVOHOME_PASSWORD. Draai dan:
    docker compose run --rm verwarming-check python3 -m scripts.evohome_login
"""
from __future__ import annotations

import asyncio
import os

import aiohttp
from dotenv import load_dotenv
from evohomeasync2 import AbstractTokenManager, EvohomeClient


class SpikeTokenManager(AbstractTokenManager):
    """Minimale token-manager voor de spike: logt in met e-mail/wachtwoord en
    bewaart het token niet (eenmalige login). De echte client krijgt later wel
    token-persistentie, want de evohome-login is gerate-limit."""

    async def save_access_token(self) -> None:
        return None


async def _main() -> None:
    load_dotenv()
    user = os.environ.get("EVOHOME_USERNAME", "").strip()
    pw = os.environ.get("EVOHOME_PASSWORD", "").strip()
    if not user or not pw:
        raise SystemExit("Zet eerst EVOHOME_USERNAME en EVOHOME_PASSWORD in app.env.")

    async with aiohttp.ClientSession() as session:
        tm = SpikeTokenManager(user, pw, session)
        client = EvohomeClient(tm, websession=session)
        await client.update()
        print("Ingelogd bij Total Connect Comfort.\n")
        for loc in client.locations:
            print("== Huis: %s (id=%s) ==" % (loc.name, loc.id))
            for gwy in loc.gateways:
                for tcs in gwy.systems:
                    for z in tcs.zones:
                        faults = [f.get("faultType") for f in (z.active_faults or [])]
                        storing = ("  STORING: " + ",".join(faults)) if faults else ""
                        print("  [%s] %-22s nu %s  doel %s  modus %s%s" % (
                            z.id, z.name, z.temperature, z.target_heat_temperature,
                            z.mode, storing))
            print()
    print("Klaar - dit zijn de zones die we aan kamers kunnen koppelen.")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
