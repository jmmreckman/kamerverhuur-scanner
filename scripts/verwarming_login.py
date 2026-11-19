#!/usr/bin/env python3
"""Eenmalige Tado-login op de VPS (OAuth2 device-flow).

Draai dit één keer op de server, bijvoorbeeld:

    docker compose run --rm verwarming-check python3 -m scripts.verwarming_login

Je krijgt een link; open die op een toestel met browser, log in bij Tado en
keur goed. Het refresh-token wordt bewaard in <state_dir>/tado_token.json (op
het data-volume, dus het overleeft deploys). Daarna leest/stuurt de
verwarming-check-service zelfstandig - geen browser meer nodig.
"""
from __future__ import annotations

from dotenv import load_dotenv

from kamerverhuur_scanner import tado_client
from kamerverhuur_scanner.config import Config, ConfigError


def main() -> None:
    load_dotenv()
    try:
        config = Config.load()
    except ConfigError as exc:
        raise SystemExit(f"Configuratiefout: {exc}")

    token_file = config.tado_token_pad()
    device = tado_client.start_device_login()
    print("\n>> Open deze link, log in bij Tado en keur goed:")
    print("   " + device["verification_uri_complete"])
    print("   (code %s, verloopt over %ss)\n" % (device["user_code"], device["expires_in"]))
    tado_client.voltooi_device_login(token_file, device)
    print("Token bewaard in: %s\n" % token_file)

    # Meteen even uitlezen als bevestiging.
    client = tado_client.TadoClient(token_file)
    homes = client.get_homes()
    print("Gevonden huizen (home-id's):")
    for h in homes:
        print("  - %s (id=%s)" % (h.get("name"), h.get("id")))
    print("\nKlaar. De verwarming-check-service kan nu uitlezen en sturen.")


if __name__ == "__main__":
    main()
