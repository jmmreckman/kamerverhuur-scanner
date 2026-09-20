#!/usr/bin/env python3
"""Tijdelijk diagnose-hulpje voor de Move.nl-bron: logt in, toont de token-claims en
probeert de GraphQL-call met verschillende headers/endpoints, zodat we zien welke
combinatie de 401 oplost. Toont GEEN wachtwoord of ruw token."""
from __future__ import annotations

import base64
import json

import requests

from rotterdam_scanner import move_scrape as m
from rotterdam_scanner.config import load_config


def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def main() -> None:
    c = load_config()
    if not (c.move_email and c.move_password and c.move_dossier_id):
        print("MOVE_* env ontbreekt (email/password/dossier).")
        return
    s = requests.Session()
    s.headers.update({"User-Agent": m._UA})
    token = m._login(s, c.move_email, c.move_password)
    cl = _claims(token)
    print("LOGIN OK. iss:", cl.get("iss"), "| aud:", cl.get("aud"))

    data = m._query_pagina(s, token, c.move_dossier_id, None)
    found = (
        (((data.get("data") or {}).get("searchDossier") or {}).get("searcher") or {}).get("foundObjects") or {}
    )
    edges = found.get("edges") or []
    woningen = m.parse_move_woningen(edges)
    print(f"EERSTE PAGINA: {len(edges)} woningen opgehaald, {len(woningen)} te koop na filter.")
    print("hasNextPage:", (found.get("pageInfo") or {}).get("hasNextPage"))
    for w in woningen[:3]:
        print(f"  - {w.straatnaam} {w.huisnummer}{w.toevoeging}, {w.postcode} {w.woonplaats} | "
              f"{w.oppervlakte_advertentie} m² | € {w.prijs}")


if __name__ == "__main__":
    main()
