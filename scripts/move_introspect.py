#!/usr/bin/env python3
"""Ontdek de echte veldnamen op het Move `ExchangeObject` ZONDER introspectie
(die is op de Move-API volledig dichtgezet: __schema.types én __type zijn geblokkeerd).

Truc: stuur één echte query met een grote lijst KANDIDAAT-veldnamen in de
exchangeObject-selectie. GraphQL valideert het hele document vóór uitvoering en
rapporteert per ongeldig veld een fout:
  - classification FieldUndefined  -> veld BESTAAT NIET;
  - classification SubSelectionRequired -> veld BESTAAT en is een object (subvelden nodig);
  - geen fout voor een kandidaat   -> veld BESTAAT en is een scalar/enum.
Zo leiden we de hele veld-inventaris af uit de foutenlijst.

Draai op de VPS:
    docker exec $(docker ps -qf name=fundazoeker) python -m scripts.move_introspect
Plak de output (de drie groepen) terug in de chat.
"""
from __future__ import annotations

import re
import sys

import requests

from rotterdam_scanner import move_scrape
from rotterdam_scanner.config import load_config

# Kandidaat-veldnamen (Engels + wat NL-gokjes) voor wat we zoeken. De bekend-geldige
# onderaan dienen als sanity-check (die mogen nooit als 'bestaat niet' terugkomen).
_KANDIDATEN = [
    # eigendom / erfpacht
    "ownership", "ownershipType", "ownershipSituation", "ownershipStatus", "propertyOwnership",
    "erfpacht", "leasehold", "groundLease", "groundLeaseType", "canon", "groundLeaseAmount",
    # VvE
    "vve", "vveContribution", "vveContributionPerMonth", "monthlyContribution",
    "serviceCosts", "serviceCharge", "ownersAssociation", "hoa", "hoaContribution",
    # omschrijving / tekst
    "description", "descriptionLong", "longDescription", "fullDescription", "body",
    "text", "salesText", "advertisementText", "marketingText",
    # energie
    "energyLabel", "energyClass", "energyLabelValidUntil",
    # kadaster
    "cadastral", "cadastralDesignation", "parcel", "parcelNumber", "section", "municipality",
    # bijzonderheden / stadsgezicht / monument
    "particularities", "features", "characteristics", "specialFeatures",
    "protectedCityscape", "protectedTownscape", "monument", "monumentalStatus", "listedStatus",
    # bouw / gebruik / aanvaarding
    "constructionYear", "buildYear", "yearOfConstruction",
    "acceptance", "availability", "currentUse", "currentUsage", "usageType", "destination",
    "numberOfRooms", "numberOfBedrooms", "livingArea", "plotArea", "volume",
    # bekend-geldig (sanity-check)
    "objectDetailedType", "woonOppervlakte", "perceelOppervlakte", "aantalKamers",
    "status", "address", "koopPrice",
]


def _query(velden: list[str]) -> str:
    seln = "\n            ".join(dict.fromkeys(velden))
    return f"""
query Velden($dossierId: ID!, $first: Int!) {{
  searchDossier(id: $dossierId) {{
    searcher {{ foundObjects(first: $first) {{ edges {{ node {{ exchangeObject {{
            {seln}
    }} }} }} }} }}
  }}
}}"""


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
        return resp.json(), resp.status_code
    except ValueError:
        return {"_raw": resp.text[:300]}, resp.status_code


# graphql-java zet de validatiesoort in de message: "Validation error (FieldUndefined@[pad]) : ..."
# extensions.classification is altijd generiek "ValidationError", dus parsen we de message.
_SOORT_PAD_RE = re.compile(r"\((\w+)@\[([^\]]+)\]\)")


def _soort_en_veld(msg: str) -> tuple[str | None, str | None]:
    m = _SOORT_PAD_RE.search(msg or "")
    if not m:
        return None, None
    return m.group(1), m.group(2).split("/")[-1]


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

    data, status = _post(session, token, _query(_KANDIDATEN),
                         {"dossierId": config.move_dossier_id, "first": 1})
    errors = data.get("errors") or []
    print(f"(aantal validatiefouten terug: {len(errors)})")
    niet_bestaand: set[str] = set()
    object_velden: set[str] = set()
    for err in errors:
        soort, veld = _soort_en_veld(err.get("message", ""))
        if not veld:
            continue
        if soort == "FieldUndefined":
            niet_bestaand.add(veld)
        elif soort in ("SubSelectionRequired", "SubselectionRequired", "SubselectionNotAllowed"):
            object_velden.add(veld)

    getest = list(dict.fromkeys(_KANDIDATEN))
    scalar_velden = [v for v in getest if v not in niet_bestaand and v not in object_velden]

    if not errors and not data.get("data"):
        print("Onverwacht antwoord (geen errors, geen data). Ruwe respons:")
        print(str(data)[:800])
        print("\n=> Val terug op de DevTools-route.")
        return 2

    print("=== BESTAAT (scalar/enum) ===")
    for v in scalar_velden:
        print(f"  {v}")
    print("\n=== BESTAAT (object - subvelden nodig) ===")
    for v in sorted(object_velden):
        print(f"  {v}")
    print("\n=== bestaat NIET ===")
    print("  " + ", ".join(sorted(niet_bestaand)))
    print("\nPlak de eerste twee groepen terug in de chat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
