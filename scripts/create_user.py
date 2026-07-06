#!/usr/bin/env python3
"""Voegt een gebruiker toe (of wijzigt het wachtwoord) voor de website.

Gebruik:
    python scripts/create_user.py <gebruikersnaam>

Vraagt om een wachtwoord (2x, niet zichtbaar op het scherm) en slaat de
gehashte versie op in users.json (het bestand uit USERS_FILE in .env).
"""
from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash


def main() -> int:
    if len(sys.argv) != 2:
        print("Gebruik: python scripts/create_user.py <gebruikersnaam>")
        return 1

    username = sys.argv[1].strip()
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

    users = json.loads(users_file.read_text()) if users_file.exists() else {}
    users[username] = generate_password_hash(wachtwoord)
    users_file.write_text(json.dumps(users, indent=2))

    print(f"Gebruiker '{username}' opgeslagen in '{users_file}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
