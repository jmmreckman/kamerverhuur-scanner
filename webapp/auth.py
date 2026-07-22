"""Login + pand-toegangscontrole. Gebruikersnamen, gehashte wachtwoorden en
welke panden iemand mag zien staan in users.json (zie scripts/create_user.py).
"email" en "mail_voorkeuren" zijn optioneel en zelf in te stellen via de
Mailvoorkeuren-pagina (zie kamerverhuur_scanner/mail_voorkeuren.py).

Formaat van users.json:
    {
      "jouwnaam": {
        "wachtwoord_hash": "...", "alle_panden": true, "panden": [],
        "email": "jij@example.com", "mail_voorkeuren": {"aanmeldingen": false}
      },
      "justin":   {"wachtwoord_hash": "...", "alle_panden": false, "panden": ["mahoniestraat"]}
    }
"""
from __future__ import annotations

import json
from pathlib import Path

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash


class User(UserMixin):
    def __init__(
        self, username: str, alle_panden: bool = False, panden: list[str] | None = None,
        email: str | None = None, mail_voorkeuren: dict | None = None,
    ):
        self.id = username
        self.alle_panden = alle_panden
        self.panden = panden or []
        self.email = email
        self.mail_voorkeuren = mail_voorkeuren or {}

    def heeft_toegang(self, pand_slug: str) -> bool:
        return self.alle_panden or pand_slug in self.panden

    def mag_gebruikers_beheren(self) -> bool:
        return self.alle_panden


def load_users(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def save_users(path: str, users: dict) -> None:
    Path(path).write_text(json.dumps(users, indent=2))


def zet_gebruiker(users: dict, username: str, wachtwoord: str | None, alle_panden: bool, panden: list[str]) -> dict:
    """Voegt een gebruiker toe of werkt 'm bij. Zonder wachtwoord blijft het
    bestaande wachtwoord staan (voor het bewerken van alleen de toegang)."""
    bestaand = users.get(username, {})
    wachtwoord_hash = generate_password_hash(wachtwoord) if wachtwoord else bestaand.get("wachtwoord_hash")
    if not wachtwoord_hash:
        raise ValueError("Nieuwe gebruikers hebben een wachtwoord nodig.")
    users[username] = {"wachtwoord_hash": wachtwoord_hash, "alle_panden": alle_panden, "panden": panden}
    return users


def verify_login(users: dict, username: str, password: str) -> bool:
    gebruiker = users.get(username)
    return bool(gebruiker and check_password_hash(gebruiker["wachtwoord_hash"], password))


def user_uit_gegevens(username: str, gebruiker: dict) -> User:
    return User(
        username, gebruiker.get("alle_panden", False), gebruiker.get("panden", []),
        gebruiker.get("email"), gebruiker.get("mail_voorkeuren"),
    )


def zet_mail_voorkeuren(users: dict, username: str, email: str, voorkeuren: dict[str, bool]) -> dict:
    """Zelfbedieningsupdate: een ingelogde gebruiker past alleen zijn/haar
    eigen e-mailadres en mailvoorkeuren aan (zie webapp/app.py:
    mail_voorkeuren_overzicht()) - in tegenstelling tot zet_gebruiker()
    hierboven, dat door een beheerder met toegang tot alle panden gebruikt
    wordt om ANDERE gebruikers' toegang te beheren."""
    if username not in users:
        raise ValueError(f"Gebruiker '{username}' bestaat niet.")
    users[username]["email"] = email or None
    users[username]["mail_voorkeuren"] = voorkeuren
    return users
