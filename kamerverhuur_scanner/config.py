"""Configuratie voor de kamerverhuur-scanner, geladen uit omgevingsvariabelen (.env).

Instellingen die voor alle panden gelden (dit bestand). Instellingen die per
pand verschillen (welke sheet, welke bunq-rekening, welke Drive-map) staan
in properties.json - zie kamerverhuur_scanner/properties.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


class ConfigError(RuntimeError):
    """Ontbrekende of ongeldige configuratie in .env."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"Omgevingsvariabele '{name}' ontbreekt of is leeg. "
            f"Controleer je .env bestand (zie .env.example)."
        )
    return value


@dataclass(frozen=True)
class Config:
    google_service_account_file: str
    properties_file: str

    bunq_conf_file: str
    bunq_environment: str
    bunq_api_key: str | None

    users_file: str
    flask_secret_key: str

    bedrag_tolerantie: Decimal
    vooruitbetaling_dagen: int

    @staticmethod
    def load() -> "Config":
        return Config(
            google_service_account_file=_require("GOOGLE_SERVICE_ACCOUNT_FILE"),
            properties_file=os.environ.get("PROPERTIES_FILE", "properties.json").strip(),
            bunq_conf_file=_require("BUNQ_CONF_FILE"),
            bunq_environment=os.environ.get("BUNQ_ENVIRONMENT", "PRODUCTION").strip().upper(),
            bunq_api_key=os.environ.get("BUNQ_API_KEY", "").strip() or None,
            users_file=os.environ.get("USERS_FILE", "users.json").strip(),
            flask_secret_key=_require("FLASK_SECRET_KEY"),
            bedrag_tolerantie=Decimal(os.environ.get("BEDRAG_TOLERANTIE_CENT", "1")) / Decimal(100),
            vooruitbetaling_dagen=int(os.environ.get("VOORUITBETALING_DAGEN", "14")),
        )
