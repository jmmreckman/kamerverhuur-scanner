#!/usr/bin/env python3
"""Evohome-spike/login: controleert de Total Connect Comfort-inloggegevens en
leest de structuur (huizen -> kamers/zones) uit, zodat we de evohome-client op
de echte data kunnen bouwen. Gebruikt de onderhouden library `evohome-async`
(dezelfde die Home Assistant gebruikt), die de verschuivende Honeywell/Resideo-
login voor ons afhandelt.

Zet in app.env op de VPS: EVOHOME_USERNAME + EVOHOME_PASSWORD. Draai dan:
    docker compose run --rm verwarming-check python3 -m scripts.evohome_login

Het access/refresh-token wordt bewaard in <state_dir>/evohome_token.json (de
evohome-login is streng gerate-limit, dus hergebruiken we het token).
"""
from __future__ import annotations

import asyncio
import json
import os

import aiohttp
from dotenv import load_dotenv
from evohomeasync2 import AbstractTokenManager, EvohomeClient


class FileTokenManager(AbstractTokenManager):
    """Token-manager die het access/refresh-token in een bestand bewaart, zodat
    we niet elke keer opnieuw hoeven in te loggen (rate limiting)."""

    def __init__(self, username, password, websession, token_file):
        super().__init__(username, password, websession)
        self._token_file = token_file
        if os.path.exists(token_file):
            try:
                with open(token_file) as f:
                    self.import_access_token(json.load(f))
            except Exception:
                pass

    async def save_access_token(self) -> None:
        os.makedirs(os.path.dirname(self._token_file) or ".", exist_ok=True)
        with open(self._token_file, "w") as f:
            json.dump(self.export_access_token(), f)
        try:
            os.chmod(self._token_file, 0o600)
        except OSError:
            pass


async def _main() -> None:
    load_dotenv()
    user = os.environ.get("EVOHOME_USERNAME", "").strip()
    pw = os.environ.get("EVOHOME_PASSWORD", "").strip()
    if not user or not pw:
        raise SystemExit("Zet eerst EVOHOME_USERNAME en EVOHOME_PASSWORD in app.env.")
    state_dir = os.environ.get("STATE_DIR", ".").strip() or "."
    token_file = (os.environ.get("EVOHOME_TOKEN_FILE", "").strip()
                  or os.path.join(state_dir, "evohome_token.json"))

    async with aiohttp.ClientSession() as session:
        tm = FileTokenManager(user, pw, session, token_file)
        client = EvohomeClient(tm, websession=session)
        await client.update()
        print("Ingelogd (user_id=%s)\n" % client.user_id)
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
    print("Klaar. Token bewaard in: %s" % token_file)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
