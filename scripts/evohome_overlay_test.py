#!/usr/bin/env python3
"""Eenmalige, veilige schrijf-test voor evohome: zet EEN zone kort op een
testtemperatuur en zet 'm daarna gegarandeerd terug op de oorspronkelijke stand
(ook als er onderweg iets misgaat - het herstel staat in een finally).

Hardgecodeerd op Dordtselaan / "St.3 slaapkamer" met een naam-check, zodat er
nooit per ongeluk een andere (verhuurde) kamer wordt aangeraakt.

Draaien op de VPS:
    docker compose run --rm verwarming-check python3 -m scripts.evohome_overlay_test
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

import aiohttp
from dotenv import load_dotenv
from evohomeasync2 import AbstractTokenManager, EvohomeClient

from kamerverhuur_scanner.config import Config

LOC_NAAM = "Dordtselaan"
ZONE_NAAM = "St.3 slaapkamer"
TEST_TEMP = 13.0


class FileTokenManager(AbstractTokenManager):
    def __init__(self, user, pw, session, token_file):
        super().__init__(user, pw, session)
        self._token_file = token_file
        try:
            with open(token_file) as f:
                d = json.load(f)
            self._access_token = d["access_token"]
            self._access_token_expires = datetime.fromisoformat(d["access_token_expires"])
            self._refresh_token = d.get("refresh_token", "")
        except Exception:
            pass

    async def save_access_token(self) -> None:
        with open(self._token_file, "w") as f:
            json.dump({"access_token": self._access_token,
                       "access_token_expires": self._access_token_expires.isoformat(),
                       "refresh_token": self._refresh_token}, f)


async def _vind_zone(client):
    for loc in client.locations:
        if (loc.name or "") != LOC_NAAM:
            continue
        for gwy in loc.gateways:
            for tcs in gwy.systems:
                for z in tcs.zones:
                    if z.name == ZONE_NAAM:
                        return z
    return None


async def _main() -> None:
    load_dotenv()
    config = Config.load()
    async with aiohttp.ClientSession() as session:
        tm = FileTokenManager(config.evohome_username, config.evohome_password,
                              session, config.evohome_token_pad())
        client = EvohomeClient(tm, websession=session)
        await client.update()

        z = await _vind_zone(client)
        if z is None:
            raise SystemExit("STOP: zone '%s' in '%s' niet gevonden - niets gedaan." % (ZONE_NAAM, LOC_NAAM))
        origineel = z.target_heat_temperature
        print("Zone bevestigd: %s / %s" % (LOC_NAAM, z.name))
        print("VOOR:  nu=%s  doel=%s  modus=%s" % (z.temperature, z.target_heat_temperature, z.mode))
        if origineel is None:
            raise SystemExit("STOP: geen doeltemperatuur (offline?) - niet sturen.")

        try:
            await z.set_temperature(TEST_TEMP)
            print("\n-> override %s°C gestuurd" % TEST_TEMP)
            await asyncio.sleep(5)
            await client.update()
            z = await _vind_zone(client)
            print("NA ZETTEN:  doel=%s  modus=%s  (kan nog even 'pending' zijn)" % (
                z.target_heat_temperature, z.mode))
        finally:
            z = await _vind_zone(client)
            await z.set_temperature(origineel)
            print("\n-> teruggezet naar %s°C (oorspronkelijke stand)" % origineel)
            await asyncio.sleep(5)
            await client.update()
            z = await _vind_zone(client)
            print("NA HERSTEL: doel=%s  modus=%s" % (z.target_heat_temperature, z.mode))


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
