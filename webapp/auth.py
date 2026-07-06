"""Simpele login voor de (twee) gebruikers van de site: gebruikersnamen en
gehashte wachtwoorden staan in users.json (zie scripts/create_user.py)."""
from __future__ import annotations

import json
from pathlib import Path

from flask_login import UserMixin
from werkzeug.security import check_password_hash


class User(UserMixin):
    def __init__(self, username: str):
        self.id = username


def load_users(path: str) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def verify_login(users: dict[str, str], username: str, password: str) -> bool:
    password_hash = users.get(username)
    return bool(password_hash and check_password_hash(password_hash, password))
