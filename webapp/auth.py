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
        test_account: bool = False, kleurenherkenning: bool = False,
    ):
        self.id = username
        self.alle_panden = alle_panden
        self.panden = panden or []
        self.email = email
        self.mail_voorkeuren = mail_voorkeuren or {}
        self.test_account = test_account
        # Persoonlijke voorkeur: kleurt de site-accent mee in de herkenningskleur
        # van het pand waar je in zit (zie webapp/templates/base.html).
        self.kleurenherkenning = kleurenherkenning

    def heeft_toegang(self, pand_slug: str) -> bool:
        return self.alle_panden or pand_slug in self.panden

    def mag_gebruikers_beheren(self) -> bool:
        # Een testaccount mag rondkijken in het gebruikersbeheer, maar de echte
        # wijzig-acties (aanmaken/bewerken/verwijderen) worden geblokkeerd door
        # de testaccount-check in webapp/app.py - niet hier, zodat de pagina's
        # gewoon zichtbaar blijven.
        return self.alle_panden

    def is_test_account(self) -> bool:
        return self.test_account


def load_users(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def save_users(path: str, users: dict) -> None:
    Path(path).write_text(json.dumps(users, indent=2))


def zet_gebruiker(
    users: dict, username: str, wachtwoord: str | None, alle_panden: bool, panden: list[str],
    test_account: bool = False, kleurenherkenning: bool = False,
) -> dict:
    """Voegt een gebruiker toe of werkt 'm bij. Zonder wachtwoord blijft het
    bestaande wachtwoord staan (voor het bewerken van alleen de toegang).
    Bestaande velden die deze functie niet zelf zet (e-mail, mailvoorkeuren)
    blijven behouden - alleen wachtwoord, pand-toegang, de testaccount-vlag en
    de kleurenherkenning-voorkeur worden overschreven."""
    bestaand = users.get(username, {})
    wachtwoord_hash = generate_password_hash(wachtwoord) if wachtwoord else bestaand.get("wachtwoord_hash")
    if not wachtwoord_hash:
        raise ValueError("Nieuwe gebruikers hebben een wachtwoord nodig.")
    gebruiker = dict(bestaand)
    gebruiker["wachtwoord_hash"] = wachtwoord_hash
    gebruiker["alle_panden"] = alle_panden
    gebruiker["panden"] = panden
    gebruiker["test_account"] = test_account
    gebruiker["kleurenherkenning"] = kleurenherkenning
    users[username] = gebruiker
    return users


def verify_login(users: dict, username: str, password: str) -> bool:
    gebruiker = users.get(username)
    return bool(gebruiker and check_password_hash(gebruiker["wachtwoord_hash"], password))


def user_uit_gegevens(username: str, gebruiker: dict) -> User:
    return User(
        username, gebruiker.get("alle_panden", False), gebruiker.get("panden", []),
        gebruiker.get("email"), gebruiker.get("mail_voorkeuren"),
        gebruiker.get("test_account", False), gebruiker.get("kleurenherkenning", False),
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
