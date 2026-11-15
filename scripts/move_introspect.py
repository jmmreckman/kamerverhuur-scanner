#!/usr/bin/env python3
"""Eenmalige probe: ontdek hoe de voor ons relevante velden in de Move-GraphQL-API
heten, zodat we move_scrape.py's query kunnen uitbreiden met eigendom/erfpacht,
VvE + bijdrage en de omschrijving (en kenmerken als beschermd stadsgezicht).

Hergebruikt de bestaande Move-login (MOVE_EMAIL/MOVE_PASSWORD uit de env). Draai op
de VPS, in de deploy-map (waar docker-compose.yml staat):

    docker compose run --rm fundazoeker python -m scripts.move_introspect

Het script voert een GraphQL-introspectie uit en print alleen de types + velden waarvan
de naam op een relevant trefwoord matcht (eigendom, erfpacht, vve, bijdrage, omschrijving,
energielabel, kadaster, beschermd stadsgezicht, ...). Plak die output terug in de chat.

Staat introspectie uit op de API (sommige productie-GraphQL-servers blokkeren dat), dan
meldt het script dat; haal de detail-query dan uit de browser (DevTools > Network >
graphql: klik een woning aan en kopieer de request-query + een stuk van de response).
"""
from __future__ import annotations

import json
import re
import sys

import requests

from rotterdam_scanner import move_scrape
from rotterdam_scanner.config import load_config

_TREFWOORDEN = re.compile(
    r"eigendom|ownership|erfpacht|leasehold|canon|vve|bijdrage|contribution|service"
    r"|kadas|perce|parcel|energ|label|omschrij|description|bijzonder|beschermd"
    r"|stadsgezicht|monument|zelfbewon|clausul|bewoning|aanvaard|acceptance",
    re.IGNORECASE,
)

_INTROSPECTIE = """
query Introspectie {
  __schema {
    types {
      name
      kind
      fields(includeDeprecated: true) {
        name
        type { kind name ofType { kind name ofType { kind name } } }
      }
    }
  }
}
"""


def _typenaam(veldtype: dict) -> str:
    t = veldtype or {}
    for _ in range(3):
        if t.get("name"):
            return t["name"]
        t = t.get("ofType") or {}
    return "?"


def main() -> int:
    config = load_config()
    if not (config.move_email and config.move_password):
        print("Geen MOVE_EMAIL/MOVE_PASSWORD in de env - kan niet inloggen op Move.")
        return 1

    session = requests.Session()
    session.headers.update({"User-Agent": move_scrape._UA})
    try:
        token = move_scrape._login(session, config.move_email, config.move_password)
    except Exception as exc:  # noqa: BLE001
        print(f"Move-login mislukt: {exc}")
        return 1

    resp = session.post(
        move_scrape._GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://move.nl",
            "Referer": "https://move.nl/",
            "x-move-client-version": move_scrape._CLIENT_VERSION,
        },
        json={"operationName": "Introspectie", "query": _INTROSPECTIE},
        timeout=30,
    )
    try:
        data = resp.json()
    except ValueError:
        print(f"Geen JSON terug (HTTP {resp.status_code}): {resp.text[:300]}")
        return 2

    schema = (data.get("data") or {}).get("__schema")
    if not schema:
        print("Introspectie geweigerd of uitgeschakeld op de API.")
        print("Antwoord:", json.dumps(data)[:600])
        print("\n=> Haal de detail-query uit DevTools (Network > graphql) en plak die hier.")
        return 2

    gevonden = 0
    for t in schema.get("types") or []:
        velden = t.get("fields") or []
        hits = [f for f in velden if _TREFWOORDEN.search(f.get("name") or "")]
        if not hits:
            continue
        gevonden += len(hits)
        print(f"\n### type {t.get('name')} ({t.get('kind')})")
        for f in hits:
            print(f"  {f['name']}: {_typenaam(f.get('type'))}")

    if not gevonden:
        print("Introspectie werkte, maar geen velden matchten de trefwoorden -")
        print("plak dan toch een stuk van de detail-query/response uit DevTools.")
    else:
        print(f"\n{gevonden} relevante veld(en) gevonden. Plak deze lijst terug in de chat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
