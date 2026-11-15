#!/usr/bin/env python3
"""Eenmalige probe: ontdek hoe de voor ons relevante velden in de Move-GraphQL-API
heten (eigendom/erfpacht, VvE + bijdrage, omschrijving, beschermd stadsgezicht, ...),
zodat we move_scrape.py's query gericht kunnen uitbreiden.

Hergebruikt de bestaande Move-login (MOVE_* uit de env). Draai op de VPS:

    docker exec $(docker ps -qf name=fundazoeker) python -m scripts.move_introspect

Schema-brede introspectie (__schema.types) is op de Move-API geblokkeerd, maar
type-gerichte introspectie (__type(name:)) meestal niet. Daarom:
  1. haal via een echte query de concrete typenaam van `exchangeObject` op (__typename);
  2. introspecteer dat type (en één niveau sub-objecten) met __type(name:).
Lukt ook __type niet, dan print het script dat; haal de detail-query dan uit DevTools
(Network > graphql: woning aanklikken, request-query + stuk response kopiëren).
"""
from __future__ import annotations

import json
import sys

import requests

from rotterdam_scanner import move_scrape
from rotterdam_scanner.config import load_config

_TYPENAAM_QUERY = """
query Typenaam($dossierId: ID!, $first: Int!) {
  searchDossier(id: $dossierId) {
    searcher { foundObjects(first: $first) { edges { node { exchangeObject { __typename } } } } }
  }
}
"""

_TYPE_QUERY = """
query TypeVelden($name: String!) {
  __type(name: $name) {
    name
    fields(includeDeprecated: true) {
      name
      type { kind name ofType { kind name ofType { kind name } } }
    }
  }
}
"""


def _post(session, token, query, variables):
    resp = session.post(
        move_scrape._GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://move.nl",
            "Referer": "https://move.nl/",
            "x-move-client-version": move_scrape._CLIENT_VERSION,
        },
        json={"query": query, "variables": variables},
        timeout=30,
    )
    try:
        return resp.json()
    except ValueError:
        return {"errors": [{"message": f"HTTP {resp.status_code}: {resp.text[:200]}"}]}


def _resolve(veldtype: dict) -> tuple[str, str]:
    """(kind, naam) van een (mogelijk geneste NON_NULL/LIST) veldtype."""
    t = veldtype or {}
    for _ in range(4):
        if t.get("name"):
            return t.get("kind") or "?", t["name"]
        t = t.get("ofType") or {}
    return t.get("kind") or "?", "?"


def _introspecteer_type(session, token, naam, gezien):
    if naam in gezien:
        return []
    gezien.add(naam)
    data = _post(session, token, _TYPE_QUERY, {"name": naam})
    typ = (data.get("data") or {}).get("__type")
    if not typ:
        if data.get("errors"):
            print(f"  (introspectie van {naam} geweigerd: {data['errors'][0].get('message')})")
        return []
    print(f"\n### type {typ['name']}")
    sub_objecten = []
    for f in typ.get("fields") or []:
        kind, tnaam = _resolve(f.get("type"))
        print(f"  {f['name']}: {tnaam} ({kind})")
        if kind in ("OBJECT", "INTERFACE") and tnaam not in ("?",):
            sub_objecten.append(tnaam)
    return sub_objecten


def main() -> int:
    config = load_config()
    if not (config.move_email and config.move_password and config.move_dossier_id):
        print("MOVE_EMAIL/MOVE_PASSWORD/MOVE_DOSSIER_ID ontbreken in de env.")
        return 1

    session = requests.Session()
    session.headers.update({"User-Agent": move_scrape._UA})
    try:
        token = move_scrape._login(session, config.move_email, config.move_password)
    except Exception as exc:  # noqa: BLE001
        print(f"Move-login mislukt: {exc}")
        return 1

    # 1. concrete typenaam van exchangeObject ophalen via een echte query.
    data = _post(session, token, _TYPENAAM_QUERY, {"dossierId": config.move_dossier_id, "first": 1})
    try:
        edges = data["data"]["searchDossier"]["searcher"]["foundObjects"]["edges"]
        typenaam = edges[0]["node"]["exchangeObject"]["__typename"]
    except (KeyError, IndexError, TypeError):
        print("Kon de objecttypenaam niet ophalen. Antwoord:", json.dumps(data)[:500])
        print("\n=> Haal de detail-query uit DevTools (Network > graphql) en plak die hier.")
        return 2
    print(f"exchangeObject is van type: {typenaam}")

    # 2. dat type + één niveau sub-objecten introspecteren.
    gezien: set[str] = set()
    sub = _introspecteer_type(session, token, typenaam, gezien)
    if typenaam in gezien and not sub and not gezien - {typenaam}:
        # introspectie van het hoofdtype gaf niets terug -> waarschijnlijk geblokkeerd.
        pass
    for subnaam in sub:
        _introspecteer_type(session, token, subnaam, gezien)

    print("\nKlaar. Plak de bovenstaande typelijst(en) terug in de chat, dan koppel ik de velden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
