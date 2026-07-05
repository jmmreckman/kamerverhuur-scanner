from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    gmail_address: str
    gmail_app_password: str
    report_to: list[str]
    funda_mail_folder: str
    listing_expiry_days: int
    opkoopbescherming_woz_grens: int
    woz_api_key: str | None = None
    state_path: Path = field(default_factory=lambda: BASE_DIR / "data" / "state.json")

    @property
    def imap_host(self) -> str:
        return "imap.gmail.com"

    @property
    def smtp_host(self) -> str:
        return "smtp.gmail.com"

    @property
    def smtp_port(self) -> int:
        return 465


def load_config(env_path: Path | None = None) -> Config:
    load_dotenv(env_path or BASE_DIR / ".env")

    gmail_address = _require("SCANNER_GMAIL_ADDRESS")
    gmail_app_password = _require("SCANNER_GMAIL_APP_PASSWORD")
    report_to_raw = os.environ.get("REPORT_TO_ADDRESS", gmail_address)
    report_to = [addr.strip() for addr in report_to_raw.split(",") if addr.strip()]

    return Config(
        gmail_address=gmail_address,
        gmail_app_password=gmail_app_password,
        report_to=report_to,
        funda_mail_folder=os.environ.get("FUNDA_MAIL_FOLDER", "INBOX"),
        listing_expiry_days=int(os.environ.get("LISTING_EXPIRY_DAYS", "60")),
        opkoopbescherming_woz_grens=int(os.environ.get("OPKOOPBESCHERMING_WOZ_GRENS", "470000")),
        woz_api_key=os.environ.get("WOZ_API_KEY") or None,
    )


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Omgevingsvariabele {name} ontbreekt. Kopieer .env.example naar .env en vul hem in."
        )
    return value
