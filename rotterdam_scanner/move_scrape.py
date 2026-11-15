"""Beste bron voor kansen.steenhub.nl: het volledige, altijd actuele NVM-/Move.nl-
aanbod uit je eigen zoekopdracht-dossier - mét m², objecttype en verkoopstatus.

De Move.nl-mails verstoppen de woningen sinds kort achter een inlogknop, dus lezen
we het dossier rechtstreeks uit via de Move-API. Move gebruikt Keycloak (OIDC); we
loggen in met de authorization-code + PKCE-flow (puur via requests, geen browser) en
bevragen daarna de GraphQL-API met een bearer-token. De inloggegevens komen uit de
config (VPS-secret), nooit uit de repo.

Levert dezelfde FundaListing-objecten als de andere bronnen (met bron="nvm"), zodat
alles via exact dezelfde pipeline loopt en op object_id ontdubbelt met Funda.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import secrets

import requests

from .config import Config
from .eigendom import classificeer_eigendom
from .funda_mail import FundaListing, _maak_object_id
from .vve import classificeer_vve, parse_vve_bijdrage
from .woningkenmerken import classificeer_woningtype
from .zelfbewoning import classificeer_zelfbewoning

logger = logging.getLogger(__name__)

# Belangrijk: Move draait Keycloak achter zijn eigen adres (move.nl/auth). De API
# (api.move.nl/graphql) accepteert alleen tokens waarvan de 'iss' exact
# https://move.nl/auth/realms/move is - een token rechtstreeks van
# auth.realworks.nl (zelfde Keycloak, andere issuer-URL) wordt geweigerd (401).
# Dus de héle OIDC-flow via move.nl/auth uitvoeren.
_AUTH_URL = "https://move.nl/auth/realms/move/protocol/openid-connect/auth"
_TOKEN_URL = "https://move.nl/auth/realms/move/protocol/openid-connect/token"
_GRAPHQL_URL = "https://api.move.nl/graphql"
_CLIENT_ID = "move-client"
_REDIRECT_URI = "https://move.nl/"
# De webapp stuurt deze header mee; we bootsen 'm na (waarde mag verouderen, de
# gateway lijkt vooral op aanwezigheid + geldig token te letten).
_CLIENT_VERSION = "62-8051985dc"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_PAGE_SIZE = 50
_MAX_PAGINAS = 60  # veiligheidsgrens: 60 x 50 = 3000 woningen

# Alleen daadwerkelijk te koop staande woningen meenemen; verkocht/ingetrokken slaan
# we bij de bron al over (dit is precies de meerwaarde van de verkoopstatus).
_TE_KOOP_STATUS = re.compile(r"BESCHIKBAAR|BOD", re.IGNORECASE)
_FORM_ACTION_RE = re.compile(r'<form[^>]+action="([^"]+)"', re.IGNORECASE)
_PRIJS_RE = re.compile(r"([\d][\d.]*)")

# De query is 1-op-1 die van de Move.nl-webapp (SearchDossierViewObjectsWithCursorQuery).
_QUERY = """query SearchDossierViewObjectsWithCursorQuery($dossierId: ID!, $filter: SearcherObjectFilter, $first: Int = 0, $cursor: String) {
  searchDossier(id: $dossierId) {
    id
    searcher {
      id
      foundObjects(filter: $filter, first: $first, cursor: $cursor) {
        edges {
          cursor
          node {
            id
            exchangeObject {
              id
              address { street nr nrExtension city zipCode }
              koopPrice { formatMoneyLong formatMoneyShort }
              woonOppervlakte
              perceelOppervlakte
              aantalKamers
              status
              objectDetailedType
              aanbiedingsTekst
              kenmerkSections { name kenmerken { label value } }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}"""


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _login(session: requests.Session, email: str, password: str) -> str:
    """Voer de Keycloak authorization-code + PKCE-flow uit en geef een access-token
    terug. Gooit een RuntimeError met een duidelijke reden bij mislukking."""
    verifier, challenge = _pkce()
    auth_params = {
        "client_id": _CLIENT_ID,
        "redirect_uri": _REDIRECT_URI,
        "response_type": "code",
        "scope": "openid",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": secrets.token_urlsafe(16),
        "nonce": secrets.token_urlsafe(16),
        "response_mode": "query",
    }
    resp = session.get(_AUTH_URL, params=auth_params, timeout=30)
    resp.raise_for_status()
    match = _FORM_ACTION_RE.search(resp.text)
    if not match:
        raise RuntimeError("Move-login: kon het Keycloak-inlogformulier niet vinden (sjabloon gewijzigd?).")
    action = match.group(1).replace("&amp;", "&")

    post = session.post(
        action,
        data={"username": email, "password": password, "credentialId": ""},
        allow_redirects=False,
        timeout=30,
    )
    locatie = post.headers.get("Location", "")
    if post.status_code not in (302, 303) or "code=" not in locatie:
        # Keycloak toont bij foute inloggegevens weer het formulier (200) i.p.v. een redirect.
        raise RuntimeError("Move-login: inloggen mislukt (verkeerde gegevens of 2FA op het account?).")
    code = _code_uit_locatie(locatie)
    if not code:
        raise RuntimeError("Move-login: geen autorisatiecode in de redirect ontvangen.")

    token_resp = session.post(
        _TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _REDIRECT_URI,
            "client_id": _CLIENT_ID,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    token_resp.raise_for_status()
    token = token_resp.json().get("access_token")
    if not token:
        raise RuntimeError("Move-login: tokenendpoint gaf geen access_token terug.")
    return token


def _code_uit_locatie(locatie: str) -> str | None:
    match = re.search(r"[?&]code=([^&]+)", locatie)
    return match.group(1) if match else None


def _query_pagina(session: requests.Session, token: str, dossier_id: str, cursor: str | None) -> dict:
    resp = session.post(
        _GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://move.nl",
            "Referer": "https://move.nl/",
            "x-move-client-version": _CLIENT_VERSION,
        },
        json={
            "operationName": "SearchDossierViewObjectsWithCursorQuery",
            "query": _QUERY,
            "variables": {
                "first": _PAGE_SIZE,
                "dossierId": dossier_id,
                "filter": {"categoryType": ["NORMAL", "SAVED"], "streetCityQuery": None},
                "cursor": cursor,
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(f"Move-GraphQL-fout: {data['errors'][:1]}")
    return data


def _prijs_uit(koop: dict | None) -> int | None:
    if not koop:
        return None
    tekst = koop.get("formatMoneyLong") or koop.get("formatMoneyShort") or ""
    match = _PRIJS_RE.search(tekst)
    if not match:
        return None
    return int(match.group(1).replace(".", ""))


def _kenmerk_lookup(obj: dict) -> dict[str, str]:
    """Plat label->waarde-woordenboek uit exchangeObject.kenmerkSections.

    Move levert de kenmerken gegroepeerd per sectie (Overdracht, Bouwvorm, VvE
    checklist, Kadastrale gegevens, ...); voor onze filters is een platte lookup op
    (kleine letters) label genoeg - de relevante labels zijn uniek genoeg
    ('Eigendomssituatie', 'Bijdrage VVE p/m', 'Periodieke bijdrage', 'Soort object')."""
    lookup: dict[str, str] = {}
    for sectie in obj.get("kenmerkSections") or []:
        for kenmerk in (sectie or {}).get("kenmerken") or []:
            label = (kenmerk or {}).get("label")
            waarde = (kenmerk or {}).get("value")
            if label and waarde is not None:
                lookup[label.strip().lower()] = str(waarde).strip()
    return lookup


def _vve_signaal(periodiek: str | None) -> bool | None:
    """Expliciet ja/nee uit de VvE-checklist-regel 'Periodieke bijdrage: Ja (...)'."""
    if not periodiek:
        return None
    low = periodiek.strip().lower()
    if low.startswith("ja"):
        return True
    if low.startswith("nee") or low.startswith("geen"):
        return False
    return None


def _kenmerken_uit_object(obj: dict) -> dict:
    """Leidt de filter-velden (eigendom, VvE, zelfbewoning) af uit de Move-kenmerken +
    advertentietekst via de pure classificatielagen. Levert een dict met precies de
    extra FundaListing-velden, zodat parse_move_woningen 'm direct kan uitpakken."""
    lookup = _kenmerk_lookup(obj)
    tekst = obj.get("aanbiedingsTekst") or ""
    woningtype = classificeer_woningtype(obj.get("objectDetailedType"))

    eigendom = classificeer_eigendom(lookup.get("eigendomssituatie"), tekst)

    bijdrage_raw = lookup.get("bijdrage vve p/m") or lookup.get("periodieke bijdrage")
    vve = classificeer_vve(
        woningtype,
        parse_vve_bijdrage(bijdrage_raw),
        _vve_signaal(lookup.get("periodieke bijdrage")),
    )
    bijdrage = vve["bijdrage_pm"]

    zb = classificeer_zelfbewoning(tekst)

    return {
        "eigendom_soort": eigendom["soort"],
        "heeft_vve": vve["heeft_vve"],
        "vve_bijdrage_pm": float(bijdrage) if bijdrage is not None else None,
        "zelfbewoningsplicht": zb["zelfbewoningsplicht"],
        "niet_zelfbewoningsclausule": zb["niet_zelfbewoningsclausule"],
        "anti_speculatie": zb["anti_speculatie"],
    }


def parse_move_woningen(edges: list[dict]) -> list[FundaListing]:
    """Zet de GraphQL-edges om naar FundaListing-objecten (bron='nvm'). Verkochte/
    ingetrokken woningen worden overgeslagen op basis van de status."""
    woningen: dict[str, FundaListing] = {}
    for edge in edges:
        obj = ((edge or {}).get("node") or {}).get("exchangeObject") or {}
        adres = obj.get("address") or {}
        status = (obj.get("status") or "").strip()
        if status and not _TE_KOOP_STATUS.search(status):
            continue  # verkocht/onder voorbehoud/ingetrokken - geen kans meer
        postcode = (adres.get("zipCode") or "").replace(" ", "")
        huisnummer = adres.get("nr")
        toevoeging = (adres.get("nrExtension") or "").strip().upper()
        if huisnummer is None or not postcode:
            continue
        huisnummer = str(huisnummer)
        object_id = _maak_object_id(postcode, huisnummer, toevoeging)
        if not object_id:
            continue
        opp = obj.get("woonOppervlakte")
        perceel = obj.get("perceelOppervlakte")
        kenmerken = _kenmerken_uit_object(obj)
        woningen.setdefault(
            object_id,
            FundaListing(
                object_id=object_id,
                url="",  # Move heeft geen Funda-link; de Funda-bron vult die later aan
                straatnaam=(adres.get("street") or "").strip() or None,
                huisnummer=huisnummer,
                toevoeging=toevoeging,
                postcode=postcode,
                woonplaats=(adres.get("city") or "").strip() or None,
                prijs=_prijs_uit(obj.get("koopPrice")),
                oppervlakte_advertentie=int(opp) if isinstance(opp, (int, float)) else None,
                woningtype_detail=(obj.get("objectDetailedType") or None),
                perceel_oppervlakte=int(perceel) if isinstance(perceel, (int, float)) else None,
                bron="nvm",
                **kenmerken,
            ),
        )
    return list(woningen.values())


def haal_move_woningen(config: Config) -> tuple[list[FundaListing], list[str]]:
    """Logt in op Move.nl en leest het volledige gevonden-woningen-dossier uit.

    Geeft (woningen, waarschuwingen). Fail-safe: elke storing levert een lege lijst +
    een waarschuwing op (die in het dagrapport belandt), nooit een crash."""
    if not (config.move_email and config.move_password and config.move_dossier_id):
        return [], []  # bron niet geconfigureerd -> stil overslaan

    waarschuwingen: list[str] = []
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": _UA})
        token = _login(session, config.move_email, config.move_password)

        edges: list[dict] = []
        cursor: str | None = None
        for _ in range(_MAX_PAGINAS):
            data = _query_pagina(session, token, config.move_dossier_id, cursor)
            found = (
                (((data.get("data") or {}).get("searchDossier") or {}).get("searcher") or {}).get("foundObjects")
                or {}
            )
            edges.extend(found.get("edges") or [])
            page_info = found.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break

        woningen = parse_move_woningen(edges)
        if not woningen:
            waarschuwingen.append(
                "Move-bron: ingelogd maar 0 woningen gelezen uit het dossier - controleer de "
                "MOVE_DOSSIER_URL/-ID of de zoekopdracht."
            )
        return woningen, waarschuwingen
    except Exception as exc:  # noqa: BLE001 - nooit de rest van de scan tegenhouden
        logger.warning("Move-bron mislukt: %s", exc)
        return [], [f"Move-bron kon niet uitgelezen worden: {exc}"]
