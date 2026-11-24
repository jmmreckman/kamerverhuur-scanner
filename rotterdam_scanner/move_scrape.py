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
import email
import hashlib
import imaplib
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from .config import Config
from .eigendom import classificeer_eigendom
from .funda_mail import FundaListing, _get_body, _maak_object_id
from .jsonbestand import schrijf_json_atomisch
from .verkoopstatus import categoriseer_verkoopstatus
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


# ---------------------------------------------------------------------------
# Inloggen. Move draait Keycloak met e-mail+wachtwoord en sinds kort een tweede stap:
# een eenmalige code per e-mail (OTP). Daarom:
#   1. we loggen één keer volledig in (wachtwoord + e-mailcode), en
#   2. bewaren het refresh-token in het data-volume; elke volgende run verversen we
#      stilletjes (geen code nodig). Pas als dat faalt doen we weer een verse login en
#      lezen we de code automatisch uit het scanner-Gmail (hetzelfde postvak als de
#      Funda-alerts). Geen handwerk, geen browser - puur requests + IMAP.

_FORM_RE = re.compile(r"<form\b[^>]*>.*?</form>", re.IGNORECASE | re.DOTALL)
_ACTION_RE = re.compile(r'<form\b[^>]*\baction="([^"]*)"', re.IGNORECASE)
_INPUT_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_ATTR_NAAM_RE = re.compile(r'\bname="([^"]*)"', re.IGNORECASE)
_ATTR_WAARDE_RE = re.compile(r'\bvalue="([^"]*)"', re.IGNORECASE)
_ATTR_TYPE_RE = re.compile(r'\btype="([^"]*)"', re.IGNORECASE)
# De code in de inlogmail is bv. "NMM424": enkele letters gevolgd door enkele cijfers.
_OTP_RE = re.compile(r"\b([A-Z]{2,5}[0-9]{2,5})\b")
_OTP_NUMERIEK_RE = re.compile(r"\b([0-9]{5,8})\b")
_INVULBARE_TYPES = {"", "text", "email", "password", "number", "tel"}
_VASTE_VELDEN = {"rememberme", "credentialid"}


def _unescape(tekst: str) -> str:
    return (
        tekst.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def _parse_login_form(html_tekst: str) -> tuple[str, dict[str, tuple[str, str]]]:
    """Zoek het eerste interactieve <form> (met een invulbaar veld) en geef
    (action-URL, {veldnaam: (waarde, type)}) terug. Zo werkt dezelfde functie voor
    zowel het wachtwoord- als het OTP-formulier, ongeacht de exacte veldnamen."""
    for form in _FORM_RE.findall(html_tekst):
        velden: dict[str, tuple[str, str]] = {}
        invulbaar = False
        for tag in _INPUT_RE.findall(form):
            naam_m = _ATTR_NAAM_RE.search(tag)
            if not naam_m:
                continue
            naam = naam_m.group(1)
            waarde_m = _ATTR_WAARDE_RE.search(tag)
            type_m = _ATTR_TYPE_RE.search(tag)
            waarde = _unescape(waarde_m.group(1)) if waarde_m else ""
            veldtype = type_m.group(1).lower() if type_m else ""
            velden[naam] = (waarde, veldtype)
            if veldtype in _INVULBARE_TYPES:
                invulbaar = True
        if not invulbaar:
            continue
        actie_m = _ACTION_RE.search(form)
        actie = _unescape(actie_m.group(1)) if actie_m else ""
        return actie, velden
    raise RuntimeError("Move-login: geen invulbaar formulier gevonden (sjabloon gewijzigd?).")


def _heeft_wachtwoordveld(velden: dict[str, tuple[str, str]]) -> bool:
    return any(veldtype == "password" for _, veldtype in velden.values())


def _kies_otp_veld(velden: dict[str, tuple[str, str]]) -> str:
    """Welk veld de e-mailcode in moet: het eerste invulbare, lege veld dat geen vast
    Keycloak-veld is (rememberMe/credentialId)."""
    for naam, (waarde, veldtype) in velden.items():
        if naam.lower() in _VASTE_VELDEN:
            continue
        if veldtype in _INVULBARE_TYPES and not waarde:
            return naam
    raise RuntimeError("Move-login: geen invoerveld voor de e-mailcode gevonden.")


def _extract_otp_code(tekst: str) -> str | None:
    """Haal de eenmalige code uit de tekst/HTML van de inlogmail."""
    match = _OTP_RE.search(tekst)
    if match:
        return match.group(1)
    match = _OTP_NUMERIEK_RE.search(tekst)
    return match.group(1) if match else None


def _bericht_datum(bericht) -> datetime | None:
    ruwe = bericht.get("Date")
    if not ruwe:
        return None
    try:
        dt = parsedate_to_datetime(ruwe)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _lees_otp_code_uit_mail(
    config: Config, na: datetime, pogingen: int = 10, interval: float = 3.0
) -> str:
    """Pollt het scanner-Gmail (hetzelfde postvak als de Funda-alerts) op de nieuwste
    Move-inlogmail die ná `na` binnenkwam en geeft de code terug. Gooit een RuntimeError
    als er binnen de pogingen geen code verschijnt."""
    sinds = (na - timedelta(days=1)).strftime("%d-%b-%Y")
    marge = na - timedelta(seconds=60)  # klok-/afrondingsmarge
    laatste_fout = "geen verse Move-inlogmail gevonden"
    for poging in range(pogingen):
        try:
            with imaplib.IMAP4_SSL(config.imap_host) as imap:
                imap.login(config.gmail_address, config.gmail_app_password)
                imap.select(config.funda_mail_folder)
                status, data = imap.search(None, f'(SINCE "{sinds}" FROM "move")')
                if status == "OK" and data and data[0]:
                    beste_dt: datetime | None = None
                    beste_code: str | None = None
                    for msg_id in data[0].split():
                        st, msg_data = imap.fetch(msg_id, "(RFC822)")
                        if st != "OK" or not msg_data or msg_data[0] is None:
                            continue
                        bericht = email.message_from_bytes(msg_data[0][1])
                        ontvangen = _bericht_datum(bericht)
                        if ontvangen is not None and ontvangen < marge:
                            continue  # oude code (van een eerdere login) overslaan
                        code = _extract_otp_code(_get_body(bericht)) or _extract_otp_code(
                            bericht.get("Subject") or ""
                        )
                        if code and (beste_dt is None or (ontvangen or na) >= beste_dt):
                            beste_dt = ontvangen or na
                            beste_code = code
                    if beste_code:
                        return beste_code
        except Exception as exc:  # noqa: BLE001
            laatste_fout = str(exc)
        if poging < pogingen - 1:
            time.sleep(interval)
    raise RuntimeError(f"Move-login: geen e-mailcode ontvangen ({laatste_fout}).")


def _token_endpoint(session: requests.Session, data: dict) -> dict:
    resp = session.post(_TOKEN_URL, data={**data, "client_id": _CLIENT_ID}, timeout=30)
    resp.raise_for_status()
    tok = resp.json()
    if not tok.get("access_token"):
        raise RuntimeError("Move-login: tokenendpoint gaf geen access_token terug.")
    return tok


def _voer_oidc_flow(session: requests.Session, config: Config) -> dict:
    """Volledige Keycloak authorization-code + PKCE-login, mét de e-mailcode-stap.
    Geeft het hele tokenantwoord (access_token, refresh_token, ...) terug."""
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
    actie, velden = _parse_login_form(resp.text)

    data = {naam: waarde for naam, (waarde, _t) in velden.items()}
    data["username"] = config.move_email
    data["password"] = config.move_password
    data["rememberMe"] = "on"  # langere Keycloak-sessie -> minder vaak opnieuw inloggen
    post = session.post(actie, data=data, allow_redirects=False, timeout=30)

    code = (
        _code_uit_locatie(post.headers.get("Location", ""))
        if post.status_code in (302, 303)
        else None
    )
    if code is None:
        if post.status_code in (302, 303):
            raise RuntimeError("Move-login: redirect zonder autorisatiecode.")
        # 200 = of foute gegevens, of de tweede stap (e-mailcode).
        na = datetime.now(timezone.utc)
        otp_actie, otp_velden = _parse_login_form(post.text)
        if _heeft_wachtwoordveld(otp_velden):
            raise RuntimeError("Move-login: inloggen mislukt (verkeerde gegevens?).")
        code_veld = _kies_otp_veld(otp_velden)
        otp_code = _lees_otp_code_uit_mail(config, na)
        otp_data = {naam: waarde for naam, (waarde, vt) in otp_velden.items() if vt != "submit"}
        otp_data[code_veld] = otp_code
        post2 = session.post(otp_actie, data=otp_data, allow_redirects=False, timeout=30)
        code = (
            _code_uit_locatie(post2.headers.get("Location", ""))
            if post2.status_code in (302, 303)
            else None
        )
        if code is None:
            raise RuntimeError("Move-login: e-mailcode afgewezen of extra inlogstap vereist.")

    return _token_endpoint(
        session,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _REDIRECT_URI,
            "code_verifier": verifier,
        },
    )


def _ververs_token(session: requests.Session, refresh_token: str) -> dict | None:
    """Probeer een bewaarde sessie te verversen. None = mislukt (verlopen) -> verse login."""
    try:
        resp = session.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": _CLIENT_ID,
            },
            timeout=30,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    tok = resp.json()
    return tok if tok.get("access_token") else None


def _token_pad(config: Config) -> Path:
    return Path(config.state_path).parent / "move_token.json"


def _laad_opgeslagen_token(pad: Path) -> dict:
    try:
        return json.loads(pad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _bewaar_token(pad: Path, tok: dict) -> None:
    schrijf_json_atomisch(
        pad,
        {
            "access_token": tok.get("access_token"),
            "refresh_token": tok.get("refresh_token"),
            "expires_in": tok.get("expires_in"),
            "refresh_expires_in": tok.get("refresh_expires_in"),
            "obtained_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _verkrijg_access_token(session: requests.Session, config: Config) -> str:
    """Geef een geldig access-token. Ververst eerst een bewaarde sessie; lukt dat niet,
    dan een volledige login (met automatische e-mailcode). Bewaart het (vernieuwde)
    refresh-token, zodat de volgende runs geen code meer nodig hebben."""
    pad = _token_pad(config)
    opgeslagen = _laad_opgeslagen_token(pad)
    refresh_token = opgeslagen.get("refresh_token")
    if refresh_token:
        vernieuwd = _ververs_token(session, refresh_token)
        if vernieuwd:
            if not vernieuwd.get("refresh_token"):
                vernieuwd["refresh_token"] = refresh_token  # niet geroteerd -> oude houden
            _bewaar_token(pad, vernieuwd)
            return vernieuwd["access_token"]
        logger.info("Move: sessie verlopen, verse login met e-mailcode nodig.")
    tok = _voer_oidc_flow(session, config)
    _bewaar_token(pad, tok)
    return tok["access_token"]


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
    """Zet de GraphQL-edges om naar FundaListing-objecten (bron='nvm').

    We gooien verkochte/ingetrokken woningen hier NIET meer weg: de verkoopstatus wordt
    per woning meegegeven en opgeslagen, zodat een al bekende woning dagelijks een
    statusupdate krijgt (beschikbaar -> onder bod -> verkocht) en de kaart erop kan
    filteren. Een gloednieuwe woning die al afgerond is (verkocht/ingetrokken) wordt pas
    in de pipeline overgeslagen (die hoeven we niet alsnog te geocoden), zie
    _verwerk_listings."""
    woningen: dict[str, FundaListing] = {}
    for edge in edges:
        obj = ((edge or {}).get("node") or {}).get("exchangeObject") or {}
        adres = obj.get("address") or {}
        verkoopstatus = categoriseer_verkoopstatus(obj.get("status"))
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
                verkoopstatus=verkoopstatus,
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
        token = _verkrijg_access_token(session, config)

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
