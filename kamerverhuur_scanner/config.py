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
    history_worksheet: str
    google_drive_folder_id: str | None

    bunq_conf_file: str
    bunq_environment: str
    bunq_api_key: str | None
    bunq_rekening_iban: str

    users_file: str
    flask_secret_key: str

    bedrag_tolerantie: Decimal

    @staticmethod
    def load() -> "Config":
        return Config(
            google_sheet_id=_require("GOOGLE_SHEET_ID"),
            google_service_account_file=_require("GOOGLE_SERVICE_ACCOUNT_FILE"),
            google_sheet_worksheet=os.environ.get("GOOGLE_SHEET_WORKSHEET", "Mahoniestraat").strip(),
            history_worksheet=os.environ.get("GOOGLE_SHEET_HISTORY_WORKSHEET", "Historie").strip(),
            google_drive_folder_id=os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip() or None,
            bunq_conf_file=_require("BUNQ_CONF_FILE"),
            bunq_environment=os.environ.get("BUNQ_ENVIRONMENT", "PRODUCTION").strip().upper(),
            bunq_api_key=os.environ.get("BUNQ_API_KEY", "").strip() or None,
            bunq_rekening_iban=_require("BUNQ_REKENING_IBAN").replace(" ", "").upper(),
            users_file=os.environ.get("USERS_FILE", "users.json").strip(),
            flask_secret_key=_require("FLASK_SECRET_KEY"),
            bedrag_tolerantie=Decimal(os.environ.get("BEDRAG_TOLERANTIE_CENT", "1")) / Decimal(100),
        )
