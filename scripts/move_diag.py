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
    print("LOGIN OK, token opgehaald.")

    cl = _claims(token)
    print("CLAIM KEYS:", sorted(cl.keys()))
    for k in ("iss", "aud", "azp", "scope", "typ", "allowed-origins", "clientId", "client_id"):
        if k in cl:
            print(f"  {k}: {cl[k]}")
    if "resource_access" in cl:
        print("  resource_access keys:", list((cl.get("resource_access") or {}).keys()))
    if "realm_access" in cl:
        print("  realm_access:", cl.get("realm_access"))

    q = {"query": "{__typename}"}
    bearer = "Bearer " + token
    varianten = [
        ("A base       ", m._GRAPHQL_URL, {"Authorization": bearer}),
        ("B origin     ", m._GRAPHQL_URL, {"Authorization": bearer, "Origin": "https://move.nl", "Referer": "https://move.nl/"}),
        ("C apollo     ", m._GRAPHQL_URL, {"Authorization": bearer, "Origin": "https://move.nl", "Referer": "https://move.nl/", "apollographql-client-name": "move-web", "apollographql-client-version": "1.0"}),
        ("D lowercase  ", m._GRAPHQL_URL, {"authorization": "bearer " + token, "Origin": "https://move.nl"}),
        ("E xrequested ", m._GRAPHQL_URL, {"Authorization": bearer, "Origin": "https://move.nl", "X-Requested-With": "XMLHttpRequest"}),
        ("F api.move   ", "https://api.move.nl/graphql", {"Authorization": bearer, "Origin": "https://move.nl", "Referer": "https://move.nl/"}),
    ]
    for label, url, hdr in varianten:
        try:
            r = s.post(url, headers=hdr, json=q, timeout=20)
            print(label, r.status_code, r.text[:90].replace("\n", " "))
        except Exception as exc:  # noqa: BLE001
            print(label, "ERR", str(exc)[:90])


if __name__ == "__main__":
    main()
