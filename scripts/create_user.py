#!/usr/bin/env python3
"""Voegt een gebruiker toe (of wijzigt wachtwoord/toegang) voor de website.

Gebruik:
    python scripts/create_user.py <gebruikersnaam> --alle-panden
    python scripts/create_user.py <gebruikersnaam> --panden mahoniestraat,pand2

Vraagt om een wachtwoord (2x, niet zichtbaar op het scherm) en slaat de
gehashte versie + de opgegeven pand-toegang op in users.json (het bestand
uit USERS_FILE in .env). Bestaande gebruikers worden overschreven (handig
om een wachtwoord te wijzigen of de toegang aan te passen).
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash


def main() -> int:
    parser = argparse.ArgumentParser(description="Gebruiker aanmaken/bijwerken voor de website.")
    parser.add_argument("gebruikersnaam")
    groep = parser.add_mutually_exclusive_group(required=True)
    groep.add_argument("--alle-panden", action="store_true", help="Toegang tot alle huidige en toekomstige panden.")
    groep.add_argument("--panden", help="Komma-gescheiden lijst van pand-slugs, bv. mahoniestraat,pand2")
    args = parser.parse_args()

    load_dotenv()
    users_file = Path(os.environ.get("USERS_FILE", "users.json"))

    wachtwoord = getpass.getpass("Wachtwoord: ")
    herhaling = getpass.getpass("Herhaal wachtwoord: ")
    if wachtwoord != herhaling:
        print("Wachtwoorden komen niet overeen.")
        return 1
    if len(wachtwoord) < 8:
        print("Gebruik een wachtwoord van minimaal 8 tekens.")
        return 1

    panden = [p.strip() for p in args.panden.split(",") if p.strip()] if args.panden else []

    users = json.loads(users_file.read_text()) if users_file.exists() else {}
    users[args.gebruikersnaam] = {
        "wachtwoord_hash": generate_password_hash(wachtwoord),
        "alle_panden": args.alle_panden,
        "panden": panden,
    }
    users_file.write_text(json.dumps(users, indent=2))

    toegang = "alle panden" if args.alle_panden else f"panden: {', '.join(panden) or '(geen)'}"
    print(f"Gebruiker '{args.gebruikersnaam}' opgeslagen in '{users_file}' ({toegang}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
