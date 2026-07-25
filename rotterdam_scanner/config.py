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
    # Apify (https://apify.com) haalt het volledige actuele Funda-aanbod op voor
    # de zoek-URL's hieronder - los van de mail-alert, die alleen NIEUWE
    # woningen sinds gisteren meldt. Leeg = de Apify-scans slaan zichzelf over
    # (zie apify_scraper.is_ingesteld()) zonder de rest van de scanner te
    # breken - precies zoals RCLONE_REMOTE/KANSEN_APP_* bij de andere
    # optionele stukken van dit systeem.
    apify_api_token: str = ""
    apify_actor_id: str = "easyapi/funda-nl-scraper"
    # Eigen Funda-zoek-URL's (Koop, Huis, Rotterdam + randgemeentes) - zelf op
    # funda.nl samengesteld en de URL uit de adresbalk gekopieerd, net als bij
    # de bestaande e-mail-zoekopdracht. Pipe-gescheiden (|) omdat de URL's zelf
    # komma's kunnen bevatten.
    apify_search_urls: list[str] = field(default_factory=list)
    # Klein/vaak (dagelijks, alleen de nieuwste woningen) vs. groot/zeldzaam
    # (wekelijks, het hele aanbod - ook de basis voor de verkocht-detectie in
    # pipeline.run_apify_volledig()). Zie README voor de kostenafweging.
    apify_max_items_dagelijks: int = 150
    apify_max_items_wekelijks: int = 2000

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
        smtp_host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.environ.get("SMTP_PORT", "465")),
        smtp_username=os.environ.get("SMTP_USERNAME", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        smtp_from_email=os.environ.get("SMTP_FROM_EMAIL", ""),
        smtp_from_naam=os.environ.get("SMTP_FROM_NAAM", ""),
        kansen_app_users=_parse_kansen_app_users(os.environ.get("KANSEN_APP_USERS", "")),
        kansen_app_secret_key=os.environ.get("KANSEN_APP_SECRET_KEY", ""),
        apify_api_token=os.environ.get("APIFY_API_TOKEN", "").strip(),
        apify_actor_id=os.environ.get("APIFY_ACTOR_ID", "easyapi/funda-nl-scraper").strip(),
        apify_search_urls=[url.strip() for url in os.environ.get("APIFY_SEARCH_URLS", "").split("|") if url.strip()],
        apify_max_items_dagelijks=int(os.environ.get("APIFY_MAX_ITEMS_DAGELIJKS", "150")),
        apify_max_items_wekelijks=int(os.environ.get("APIFY_MAX_ITEMS_WEKELIJKS", "2000")),
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
