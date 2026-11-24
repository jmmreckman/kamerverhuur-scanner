#!/usr/bin/env python3
"""Bootstrap/controle van de Move.nl-login (e-mail + automatische e-mailcode).

Move loggt sinds kort in met een eenmalige code per e-mail (naast wachtwoord). De
scanner logt daarom één keer volledig in - de code wordt automatisch uit het
scanner-Gmail gelezen (hetzelfde postvak als de Funda-alerts) - en rijdt daarna op
het bewaarde refresh-token (geen code meer nodig). Draai dit script voor de eerste
keer of na een verlopen sessie.

Op de VPS:
    docker compose run --rm fundazoeker python3 -m scripts.move_login
    docker compose run --rm fundazoeker python3 -m scripts.move_login --opnieuw
"""
from __future__ import annotations

import sys

import requests

from rotterdam_scanner import move_scrape
from rotterdam_scanner.config import load_config


def main() -> int:
    opnieuw = "--opnieuw" in sys.argv
    config = load_config()
    if not (config.move_email and config.move_password and config.move_dossier_id):
        print("Move-bron niet geconfigureerd (MOVE_EMAIL/MOVE_PASSWORD/MOVE_DOSSIER_ID ontbreken).")
        return 1

    session = requests.Session()
    session.headers.update({"User-Agent": move_scrape._UA})

    pad = move_scrape._token_pad(config)
    if opnieuw:
        try:
            pad.unlink()
            print("Bewaarde sessie gewist; verse login.")
        except OSError:
            pass

    print(f"Inloggen op Move.nl als {config.move_email} ...")
    print("(Bij een verse login wacht ik ~30s op de e-mailcode in het scanner-Gmail.)")
    token = move_scrape._verkrijg_access_token(session, config)

    opgeslagen = move_scrape._laad_opgeslagen_token(pad)
    print("Ingelogd. Token bewaard in:", pad)
    if opgeslagen.get("expires_in"):
        print("  access-token geldig (s):", opgeslagen["expires_in"])
    if opgeslagen.get("refresh_expires_in"):
        print("  refresh-token geldig (s):", opgeslagen["refresh_expires_in"])

    # Smoke test: eerste pagina van het dossier lezen om token + dossier-id te bevestigen.
    data = move_scrape._query_pagina(session, token, config.move_dossier_id, None)
    found = (
        (((data.get("data") or {}).get("searchDossier") or {}).get("searcher") or {}).get("foundObjects")
        or {}
    )
    aantal = len(found.get("edges") or [])
    print(f"Dossier gelezen: {aantal} woningen op de eerste pagina. Klaar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
