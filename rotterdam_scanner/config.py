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
    # Ondergrens capaciteit voor Den Haag: een woning telt alleen als "geschikt"
    # als er minstens zoveel bewoners mogelijk zijn (max bewoners = m² // 18, cap
    # 8). Standaard 6 (gelijk aan de scanner van Wout). Rotterdam gebruikt zijn
    # eigen kamer-/oppervlaktelogica en raakt dit niet.
    den_haag_min_bewoners: int = 6
    # Funda-alertmails worden altijd via het Gmail-scanner-account (hierboven) gelezen.
    # Het dagrapport versturen kan via diezelfde Gmail SMTP, of desgewenst via een eigen
    # domein/mailbox (bijv. via de hostingpartij van je eigen website) -- vandaar deze
    # aparte, optionele SMTP-instellingen die bij leeg gewoon op Gmail terugvallen.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_naam: str = ""
    state_path: Path = field(default_factory=lambda: BASE_DIR / "data" / "state.json")
    # Login voor de kaart-website (kansen.steenhub.nl) - los van bovenstaande
    # Gmail-/SMTP-instellingen. Leeg = de website weigert te starten (zie
    # kansen_site/app.py), zodat de kaart nooit per ongeluk zonder wachtwoord
    # open komt te staan.
    kansen_app_users: dict[str, str] = field(default_factory=dict)
    kansen_app_secret_key: str = ""

    @property
    def imap_host(self) -> str:
        return "imap.gmail.com"

    @property
    def effective_smtp_username(self) -> str:
        return self.smtp_username or self.gmail_address

    @property
    def effective_smtp_password(self) -> str:
        return self.smtp_password or self.gmail_app_password

    @property
    def effective_from_email(self) -> str:
        return self.smtp_from_email or self.effective_smtp_username

    @property
    def effective_from_header(self) -> str:
        if self.smtp_from_naam:
            return f"{self.smtp_from_naam} <{self.effective_from_email}>"
        return self.effective_from_email


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
        listing_expiry_days=int(os.environ.get("LISTING_EXPIRY_DAYS", "30")),
        opkoopbescherming_woz_grens=int(os.environ.get("OPKOOPBESCHERMING_WOZ_GRENS", "470000")),
        den_haag_min_bewoners=int(os.environ.get("DEN_HAAG_MIN_BEWONERS", "6")),
        smtp_host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.environ.get("SMTP_PORT", "465")),
        smtp_username=os.environ.get("SMTP_USERNAME", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        smtp_from_email=os.environ.get("SMTP_FROM_EMAIL", ""),
        smtp_from_naam=os.environ.get("SMTP_FROM_NAAM", ""),
        kansen_app_users=_parse_kansen_app_users(os.environ.get("KANSEN_APP_USERS", "")),
        kansen_app_secret_key=os.environ.get("KANSEN_APP_SECRET_KEY", ""),
    )


def _parse_kansen_app_users(raw: str) -> dict[str, str]:
    """Formaat: "gebruiker1:wachtwoord1,gebruiker2:wachtwoord2"."""
    gebruikers = {}
    for paar in raw.split(","):
        naam, _, wachtwoord = paar.strip().partition(":")
        if naam and wachtwoord:
            gebruikers[naam] = wachtwoord
    return gebruikers


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Omgevingsvariabele {name} ontbreekt. Kopieer .env.example naar .env en vul hem in."
        )
    return value
