#!/usr/bin/env python3
"""Laatste discovery-stap: bevestig hoe we de kenmerken (eigendom/VvE/omschrijving)
het beste ophalen.

De woning-detailquery van de Move-webapp (SearchDossierViewObjectDetailQuery) bevat:
  ExchangeObject.kenmerkSections { name kenmerken { label value } }   # alle kenmerken
  ExchangeObject.aanbiedingsTekst                                     # advertentietekst
Vraag: komt kenmerkSections ook mee in de LIJST-query (dan geen extra call per woning),
of alleen via de DETAIL-query (searcherObject(id:))? Deze probe test beide en print de
echte secties/labels, zodat we Phase B op de juiste aanpak bouwen.

Draai op de VPS:
    docker exec $(docker ps -qf name=fundazoeker) python -m scripts.move_introspect
"""
from __future__ import annotations

import sys

import requests

from rotterdam_scanner import move_scrape
from rotterdam_scanner.config import load_config

_LIJST = """
query Lijst($dossierId: ID!, $first: Int!) {
  searchDossier(id: $dossierId) {
    searcher { foundObjects(first: $first) { edges { node {
      id
      exchangeObject {
        id
        objectDetailedType
        aanbiedingsTekst
        kenmerkSections { name kenmerken { label value } }
      }
    } } } }
  }
}
"""

_DETAIL = """
query Detail($searcherObjectId: ID!) {
  searcherObject(id: $searcherObjectId) {
    id
    exchangeObject {
      id
      objectDetailedType
      aanbiedingsTekst
      kenmerkSections { name kenmerken { label value } }
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


def _toon_secties(obj: dict, bron: str) -> None:
    secties = (obj or {}).get("kenmerkSections")
    tekst = (obj or {}).get("aanbiedingsTekst")
    print(f"\n[{bron}] aanbiedingsTekst: {'JA (' + str(len(tekst)) + ' tekens)' if tekst else 'leeg/null'}")
    if not secties:
        print(f"[{bron}] kenmerkSections: leeg/null")
        return
    print(f"[{bron}] kenmerkSections: {len(secties)} secties")
    for s in secties:
        print(f"  # {s.get('name')}")
        for k in s.get("kenmerken") or []:
            print(f"     {k.get('label')}: {k.get('value')}")


def main() -> int:
    config = load_config()
    if not (config.move_email and config.move_password and config.move_dossier_id):
        print("MOVE_* ontbreken in de env.")
        return 1
    session = requests.Session()
    session.headers.update({"User-Agent": move_scrape._UA})
    try:
        token = move_scrape._verkrijg_access_token(session, config)
    except Exception as exc:  # noqa: BLE001
        print(f"Move-login mislukt: {exc}")
        return 1

    # 1. lijst-query met kenmerkSections.
    data = _post(session, token, _LIJST, {"dossierId": config.move_dossier_id, "first": 1})
    if data.get("errors"):
        print("Lijst-query met kenmerkSections gaf errors:", data["errors"][:2])
    try:
        node = data["data"]["searchDossier"]["searcher"]["foundObjects"]["edges"][0]["node"]
    except (KeyError, IndexError, TypeError):
        print("Geen woning in het dossier gevonden; kan niet verder.")
        return 2
    searcher_object_id = node.get("id")
    _toon_secties(node.get("exchangeObject") or {}, "LIJST")

    # 2. detail-query (altijd, ter vergelijking).
    if searcher_object_id:
        d = _post(session, token, _DETAIL, {"searcherObjectId": searcher_object_id})
        if d.get("errors"):
            print("\nDetail-query gaf errors:", d["errors"][:2])
        obj = (((d.get("data") or {}).get("searcherObject")) or {}).get("exchangeObject") or {}
        _toon_secties(obj, "DETAIL")

    print("\nKlaar. Plak de output terug - vooral of de LIJST-variant de secties al bevat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
