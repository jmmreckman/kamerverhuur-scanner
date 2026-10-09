#!/usr/bin/env python3
"""Eenmalig script om de koppeling met bunq tot stand te brengen.

Registreert dit apparaat bij bunq met je API key en slaat de resulterende
sessie (incl. het bijbehorende sleutelpaar) op in het bestand dat in .env
staat als BUNQ_CONF_FILE. Dit hoef je maar één keer te draaien - daarna
gebruikt main.py dat bestand om verbinding te maken.

Gebruik:
    python scripts/setup_bunq.py
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bunq.sdk.context.api_context import ApiContext, ApiEnvironmentType  # noqa: E402


def main() -> int:
    load_dotenv()

    api_key = os.environ.get("BUNQ_API_KEY", "").strip()
    conf_file = os.environ.get("BUNQ_CONF_FILE", "bunq_production.conf").strip()
    environment_name = os.environ.get("BUNQ_ENVIRONMENT", "PRODUCTION").strip().upper()

    if not api_key:
        print("Zet eerst BUNQ_API_KEY in je .env bestand (je bunq API key uit de bunq-app).")
        return 1

    if os.path.exists(conf_file):
        antwoord = input(
            f"'{conf_file}' bestaat al. Opnieuw aanmaken en overschrijven? (typ 'ja' om door te gaan) "
        )
        if antwoord.strip().lower() != "ja":
            print("Geannuleerd.")
            return 0

    environment = ApiEnvironmentType.PRODUCTION if environment_name == "PRODUCTION" else ApiEnvironmentType.SANDBOX

    print(f"Registreren van dit apparaat bij bunq ({environment_name})...")
    api_context = ApiContext.create(environment, api_key, "kamerverhuur-scanner")
    api_context.save(conf_file)

    print(f"Klaar! De bunq-koppeling is opgeslagen in '{conf_file}'.")
    print("Zorg dat dit bestand NIET in git terechtkomt (staat al in .gitignore) en bewaar het veilig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
