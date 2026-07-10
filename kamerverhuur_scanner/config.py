"""Configuratie voor de kamerverhuur-scanner, geladen uit omgevingsvariabelen (.env).

Instellingen die voor alle panden gelden (dit bestand). Instellingen die per
pand verschillen (welke sheet, welke bunq-rekening, welke Drive-map) staan
in properties.json - zie kamerverhuur_scanner/properties.py.
"""
from __future__ import annotations

import json
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
    # Eigen SMTP-inloggegevens per beheerdersmailbox (e-mailadres -> wachtwoord),
    # zodat mail van die beheerder ook echt vanaf dat adres wordt ingelogd i.p.v.
    # alleen een ander From-adres te tonen - sommige providers (Strato) staan
    # een From-adres dat niet overeenkomt met het ingelogde account niet toe.
    # Staat een adres hier niet in, dan valt verstuur_email() terug op de
    # gewone SMTP_USERNAME/SMTP_FROM_EMAIL.
    smtp_wachtwoorden: dict[str, str] = field(default_factory=dict)

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
            smtp_wachtwoorden=_laad_smtp_wachtwoorden(),
        )


def _laad_smtp_wachtwoorden() -> dict[str, str]:
    ruw = os.environ.get("SMTP_WACHTWOORDEN", "").strip()
    if not ruw:
        return {}
    try:
        gegevens = json.loads(ruw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"SMTP_WACHTWOORDEN in .env is geen geldige JSON: {exc}. "
            f'Voorbeeld: {{"jurian@steenhub.nl": "wachtwoord1", "justin@steenhub.nl": "wachtwoord2"}}'
        ) from exc
    if not isinstance(gegevens, dict):
        raise ConfigError("SMTP_WACHTWOORDEN in .env moet een JSON-object zijn (e-mailadres -> wachtwoord).")
    return gegevens
