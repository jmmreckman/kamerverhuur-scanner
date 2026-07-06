"""Configuratie voor de kamerverhuur-scanner, geladen uit omgevingsvariabelen (.env)."""
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
    google_sheet_id: str
    google_service_account_file: str
    google_sheet_worksheet: str

    bunq_conf_file: str
    bunq_environment: str
    bunq_api_key: str | None

    gmail_address: str
    gmail_app_password: str
    email_to: str

    bedrag_tolerantie: Decimal

    @staticmethod
    def load() -> "Config":
        return Config(
            google_sheet_id=_require("GOOGLE_SHEET_ID"),
            google_service_account_file=_require("GOOGLE_SERVICE_ACCOUNT_FILE"),
            google_sheet_worksheet=os.environ.get("GOOGLE_SHEET_WORKSHEET", "Huurders").strip(),
            bunq_conf_file=_require("BUNQ_CONF_FILE"),
            bunq_environment=os.environ.get("BUNQ_ENVIRONMENT", "PRODUCTION").strip().upper(),
            bunq_api_key=os.environ.get("BUNQ_API_KEY", "").strip() or None,
            gmail_address=_require("GMAIL_ADDRESS"),
            gmail_app_password=_require("GMAIL_APP_PASSWORD"),
            email_to=_require("EMAIL_TO"),
            bedrag_tolerantie=Decimal(os.environ.get("BEDRAG_TOLERANTIE_CENT", "1")) / Decimal(100),
        )
