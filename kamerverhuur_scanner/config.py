"""Configuratie voor de kamerverhuur-scanner, geladen uit omgevingsvariabelen (.env).

Instellingen die voor alle panden gelden (dit bestand). Instellingen die per
pand verschillen (welke sheet, welke bunq-rekening, welke Drive-map) staan
in properties.json - zie kamerverhuur_scanner/properties.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
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
    # Niet meer gebruikt door de matchlogica zelf (die hanteert nu een vaste
    # regel: 1e t/m 17e van de maand telt voor die maand, 18e t/m einde van de
    # maand voor de maand erna - zie runner.py:_effectieve_maand). Blijft hier
    # staan zodat een bestaande .env met VOORUITBETALING_DAGEN niet stukloopt.
    vooruitbetaling_dagen: int

    # Map waar de "laatste controle"-cache (laatste_resultaat_<pand>.json) in
    # wordt opgeslagen. Moet op een blijvend gekoppeld volume staan (zie
    # deploy/app.env: STATE_DIR=/app/data) - anders is de Betalingen-pagina na
    # elke herbuild/deploy weer leeg, ook al is er niets echt kwijt.
    state_dir: str = "."

    # E-mail (betaalherinnering/ingebrekestelling) - optioneel, alleen nodig
    # als je die knoppen op de Betalingen-pagina gebruikt.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_naam: str = "Steenhub"
    email_bcc: list[str] = field(default_factory=list)
    # Aparte, smallere BCC-lijst voor de "opnieuw mailen"-herinneringen bij
    # het ondertekenen (zie webapp/ondertekenen.py) - die gaan bewust niet
    # naar alle mede-eigenaren in EMAIL_BCC, alleen naar de beheerder. Valt
    # terug op email_bcc als deze niet gezet is.
    email_bcc_beheerder: list[str] = field(default_factory=list)

    # Telefoonnummer van de beheerder, gebruikt in de automatische mail aan een
    # klusjesman (zie webapp/communicatie_ai.bouw_vakman_mail): "bel me eerst bij
    # bedragen boven 150 euro". Bewust via env, niet hardcoded in git. Leeg = de
    # mail noemt geen nummer (je vult het dan in bij het goedkeuren).
    beheerder_telefoon: str = ""

    # Voor het optionele AI-uitlezen van geuploade documenten (zie
    # kamerverhuur_scanner/document_ai.py) - alleen nodig als je die functie gebruikt.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    # rclone-remote (bv. "gdrive:vastgoed") voor het automatisch wegschrijven
    # van getekende contracten naar Drive - zie kamerverhuur_scanner/drive_sync.py.
    # Optioneel: zonder deze instelling doet die module gewoon niets.
    rclone_remote: str | None = None

    # Gmail (IMAP) voor de eenmalige backfill van historische huurder-communicatie
    # uit het persoonlijke Gmail-account (zie scripts/gmail_backfill.py en
    # webapp/mail_import.py). Optioneel: zonder deze instellingen doet de backfill
    # niets. Het wachtwoord is een Gmail app-wachtwoord (2FA aan), in te trekken na
    # de eenmalige import. gmail_eigen_adres bepaalt de richting (verzonden vs
    # ontvangen); valt terug op gmail_imap_user.
    gmail_imap_host: str = "imap.gmail.com"
    gmail_imap_user: str | None = None
    gmail_imap_password: str | None = None
    gmail_eigen_adres: str | None = None

    # Dagelijkse inname (Fase 2): twee eigen Steenhub-mailboxen die 1x per dag
    # worden uitgelezen (zie scripts/mail_inname.py en webapp/mail_inname.py).
    # onderhoud@ -> opent een onderhoudsticket, communicatie@ -> logt bij de
    # huurder + laat de AI beoordelen of er een antwoord/taak nodig is (in de
    # goedkeuringswachtrij). Optioneel: zonder user/password doet die mailbox
    # niets. IMAP via Strato (imap.strato.com). Berichten worden aan de juiste
    # huurder gekoppeld door in de mail te zoeken naar een bekend huurder-adres
    # (werkt dus ook als jij een mail doorstuurt - dan is de afzender immers jij).
    steenhub_imap_host: str = "imap.strato.com"
    onderhoud_imap_user: str | None = None
    onderhoud_imap_password: str | None = None
    communicatie_imap_user: str | None = None
    communicatie_imap_password: str | None = None

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
            state_dir=os.environ.get("STATE_DIR", ".").strip() or ".",
            smtp_host=os.environ.get("SMTP_HOST", "").strip() or None,
            smtp_port=int(os.environ.get("SMTP_PORT", "587").strip() or "587"),
            smtp_username=os.environ.get("SMTP_USERNAME", "").strip() or None,
            smtp_password=os.environ.get("SMTP_PASSWORD", "").strip() or None,
            smtp_from_email=os.environ.get("SMTP_FROM_EMAIL", "").strip() or None,
            smtp_from_naam=os.environ.get("SMTP_FROM_NAAM", "Steenhub").strip(),
            email_bcc=[e.strip() for e in os.environ.get("EMAIL_BCC", "").split(",") if e.strip()],
            email_bcc_beheerder=[
                e.strip() for e in os.environ.get("EMAIL_BCC_BEHEERDER", "").split(",") if e.strip()
            ],
            beheerder_telefoon=os.environ.get("BEHEERDER_TELEFOON", "").strip(),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip() or None,
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5").strip() or "claude-sonnet-5",
            rclone_remote=os.environ.get("RCLONE_REMOTE", "").strip() or None,
            gmail_imap_host=os.environ.get("GMAIL_IMAP_HOST", "imap.gmail.com").strip() or "imap.gmail.com",
            gmail_imap_user=os.environ.get("GMAIL_IMAP_USER", "").strip() or None,
            gmail_imap_password=os.environ.get("GMAIL_IMAP_PASSWORD", "").strip() or None,
            gmail_eigen_adres=os.environ.get("GMAIL_EIGEN_ADRES", "").strip() or None,
            steenhub_imap_host=os.environ.get("STEENHUB_IMAP_HOST", "imap.strato.com").strip() or "imap.strato.com",
            onderhoud_imap_user=os.environ.get("ONDERHOUD_IMAP_USER", "").strip() or None,
            onderhoud_imap_password=os.environ.get("ONDERHOUD_IMAP_PASSWORD", "").strip() or None,
            communicatie_imap_user=os.environ.get("COMMUNICATIE_IMAP_USER", "").strip() or None,
            communicatie_imap_password=os.environ.get("COMMUNICATIE_IMAP_PASSWORD", "").strip() or None,
        )
