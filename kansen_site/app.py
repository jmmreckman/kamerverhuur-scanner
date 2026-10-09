"""Kaart-website (kansen.steenhub.nl): toont de actieve kansen die de dagelijkse
Funda-scan al in state.json heeft verzameld, op een kaart + als lijst met filters.
Login is een simpel gedeeld wachtwoord per gebruiker (KANSEN_APP_USERS), los van
de Gmail-/SMTP-instellingen van de scanner zelf - zie rotterdam_scanner/config.py.

Starten (development): python3 -m kansen_site.app
Starten (productie): gunicorn 'kansen_site.app:create_app()'
"""
from __future__ import annotations

import hmac
import json
import re
import threading
import uuid
from urllib.parse import quote_plus
from dataclasses import asdict
from datetime import date, datetime, timezone
from functools import wraps

from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from pathlib import Path

from .throttle import LoginThrottle
from . import opkoop_rapport_pdf

from rotterdam_scanner import archief, den_haag, geocode, mail_voorkeuren, opkoop_scan, pipeline, rente_update, vergunningenindex
from rotterdam_scanner.mailer import send_mail
from rotterdam_scanner.config import Config, load_config
from rotterdam_scanner.handmatig import parse_bestand

# Eenvoudige e-mailvalidatie voor het ontvanger-veld van de concurrentie-scan: geen
# volledige RFC-check, maar genoeg om vertypte adressen ("jan@", "jan.nl") te weren.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
from rotterdam_scanner.investering import AANTAL_INVESTEERDERS, RekenUitgangspunten, bereken_rekentool
from rotterdam_scanner.investering import aantal_kamers_mogelijk as bereken_aantal_kamers_mogelijk
from rotterdam_scanner.investering import bereken_met_aantal_kamers as bereken_investering
from rotterdam_scanner.state import StateStore, bron_statistieken
from rotterdam_scanner.wwso_punten import (
    ENERGIELABEL_PUNTEN,
    KEUKEN_VOORZIENINGEN,
    SANITAIR_VOORZIENINGEN,
    GedeeldeRuimte,
    Kamer,
    Keuken,
    Woning,
    bereken_woning,
)

# Velden op de rekentool-pagina (kansen.steenhub.nl), in weergavevolgorde. `soort`
# stuurt de opmaak/parsing: "euro" en "aantal" staan gelijk aan hun opgeslagen
# waarde; "procent" wordt als heel getal getoond/ingevoerd (8, niet 0,08) en bij
# opslaan door 100 gedeeld. De keys komen exact overeen met RekenUitgangspunten.
REKENVELDEN = [
    ("koopsom", "Koopsom", "euro"),
    ("aantal_kamers", "Aantal kamers", "aantal"),
    ("aantal_investeerders", "Aantal investeerders", "aantal"),
    ("overdrachtsbelasting", "Overdrachtsbelasting", "procent"),
    ("bar", "BAR", "procent"),
    ("kale_huur_per_kamer", "Kale huur per kamer", "euro"),
    ("servicekosten_per_kamer", "Servicekosten per kamer", "euro"),
    ("vaste_kosten_per_huurder", "Vaste kosten per maand per huurder", "euro"),
    ("kosten_koper_ex_ovb", "Kosten koper (excl. overdrachtsbelasting)", "euro"),
    ("verbouwkosten", "Verbouwkosten", "euro"),
    ("rente", "Rente", "procent"),
    ("taxatie_verhouding_voor_verhoging", "Taxatieverhouding waarde vóór verhoging", "procent"),
    ("ltv", "LTV (leenbaar t.o.v. taxatie)", "procent"),
]


_PROCENT_VELDEN = {key for key, _label, soort in REKENVELDEN if soort == "procent"}

# Gemiddelde WOZ-waarde per m² in de COROP-regio Groot-Rijnmond (waar Rotterdam
# onder valt), vastgesteld 1 januari 2026 - Bijlage 1 van het WWSO-beleidsboek.
# Voorvulling voor de WWSO-rekentool; de gebruiker kan het overschrijven.
COROP_GROOT_RIJNMOND_WOZ_M2 = 3884.0

# Leesbare labels bij de WWSO-voorzieningssleutels (voor de rekentool-UI).
KEUKEN_VOORZIENING_LABELS = {
    "afzuiginstallatie": "Inbouw afzuiginstallatie",
    "kookplaat_inductie": "Inbouw kookplaat (inductie)",
    "kookplaat_keramisch": "Inbouw kookplaat (keramisch)",
    "kookplaat_gas": "Inbouw kookplaat (gas)",
    "koelkast": "Inbouw koelkast",
    "vrieskast": "Inbouw vrieskast",
    "oven_elektrisch": "Inbouw oven (elektrisch)",
    "oven_gas": "Inbouw oven (gas)",
    "magnetron": "Inbouw magnetron",
    "vaatwasser": "Inbouw vaatwasser",
    "eenhandsmengkraan": "Eénhandsmengkraan",
    "thermostatische_mengkraan": "Thermostatische mengkraan",
    "kokend_water": "Kokendwaterfunctie",
}

SANITAIR_VOORZIENING_LABELS = {
    "toilet_staand_toiletruimte": "Staand toilet in toiletruimte",
    "toilet_staand_badkamer": "Staand toilet in badkamer",
    "toilet_hangend_toiletruimte": "Hangend toilet in toiletruimte",
    "toilet_hangend_badkamer": "Hangend toilet in badkamer",
    "wastafel": "Wastafel",
    "meerpersoonswastafel": "Meerpersoonswastafel",
    "douche": "Douche",
    "bad": "Bad",
    "bad_douche": "Bad/douche-combinatie",
}

# De ruimtes/voorzieningen die je in de WWSO-rekentool kunt "toevoegen". `effect`
# koppelt het element aan een rubriek in de puntentelling; `velden` bepaalt welke
# invoer de UI toont (m2 = oppervlakte, verwarmd = verwarmingsvinkje, keuken =
# aanrechtlengte + apparatuur); `context` bepaalt of het als privé (in een kamer),
# gedeeld, of beide toe te voegen is.
WWSO_ELEMENTEN = {
    "open_keuken": {"label": "Keuken / keukenblok", "effect": "keuken",
                    "velden": ["keuken"], "context": "beide"},
    "toilet_toiletruimte": {"label": "Toilet (aparte toiletruimte)", "effect": "sanitair",
                            "key": "toilet_staand_toiletruimte", "velden": [], "context": "beide"},
    "toilet_badkamer": {"label": "Toilet (in badkamer)", "effect": "sanitair",
                        "key": "toilet_staand_badkamer", "velden": [], "context": "beide"},
    "douche": {"label": "Douche", "effect": "sanitair", "key": "douche",
               "velden": [], "context": "beide"},
    "bad_douche": {"label": "Bad/douche-combinatie", "effect": "sanitair", "key": "bad_douche",
                   "velden": [], "context": "beide"},
    "bad": {"label": "Bad", "effect": "sanitair", "key": "bad", "velden": [], "context": "beide"},
    "wastafel": {"label": "Wastafel", "effect": "sanitair", "key": "wastafel",
                 "velden": [], "context": "beide"},
    "woonkamer": {"label": "Woonkamer (vertrek)", "effect": "vertrek",
                  "velden": ["m2", "verwarmd"], "context": "gedeeld"},
    "berging": {"label": "Berging / bijkeuken / wasruimte", "effect": "overige",
                "velden": ["m2"], "context": "beide"},
    "overloop": {"label": "Gang / overloop (verkeersruimte)", "effect": "verkeer",
                 "velden": ["verwarmd"], "context": "gedeeld"},
    "tuin": {"label": "Tuin", "effect": "buitenruimte", "velden": ["m2"], "context": "beide"},
    "balkon": {"label": "Balkon / dakterras", "effect": "buitenruimte",
               "velden": ["m2"], "context": "beide"},
    "fietsenstalling": {"label": "Fietsenstalling", "effect": "buitenruimte",
                        "velden": ["m2"], "context": "gedeeld"},
}

# Vaste eigenaar(s) die het toegangsbeheer altijd mogen bedienen, ook als ze met
# hun steenhub-account inloggen (dat account staat niet in KANSEN_APP_USERS). Te
# overschrijven/uitbreiden via de env-variabele KANSEN_APP_BEHEERDERS.
_STANDAARD_BEHEERDERS = {"jmmreckman"}

# Gedeelde (markt/model-)uitgangspunten: gelden als globale standaard voor álle
# panden en zijn instelbaar op /reken-instellingen. Koopsom en aantal kamers horen
# bij de woning zelf en zijn dus géén gedeelde standaard.
_GEDEELDE_REKENVELDEN = [k for k, _l, _s in REKENVELDEN if k not in ("koopsom", "aantal_kamers")]


def _reken_defaults_pad(config) -> Path:
    return Path(config.state_path).parent / "reken_defaults.json"


# --- Toegangsbeheer (kansen-only) --------------------------------------------
# Sommige samenwerkingen lopen niet en dan wil je zo'n account de toegang tot de
# kaart ontnemen zonder het expliciet te melden: de gebruiker krijgt dan een
# neutrale storingspagina te zien i.p.v. "geen toegang". Deze lijst + het
# pogingen-logboek staan in een eigen JSON naast state.json; de users.json van
# steenhub.nl wordt hierbij nooit aangeraakt (alleen gelezen om te kunnen
# inloggen), zodat de werking van steenhub.nl ongewijzigd blijft.
def _handmatige_run_pad(config) -> Path:
    return Path(config.state_path).parent / "handmatige_run.json"


def _lees_handmatige_run(config) -> dict | None:
    """Laatste (of lopende) handmatige-toevoeg-run. Losbestaand van state.json zodat de
    uitkomst bewaard blijft nadat de gebruiker de pagina heeft verlaten."""
    try:
        with open(_handmatige_run_pad(config), encoding="utf-8") as bestand:
            data = json.load(bestand)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _schrijf_handmatige_run(config, data: dict) -> None:
    pad = _handmatige_run_pad(config)
    pad.parent.mkdir(parents=True, exist_ok=True)
    with open(pad, "w", encoding="utf-8") as bestand:
        json.dump(data, bestand, ensure_ascii=False, indent=2)


def _storing_respons():
    """Kale platte-tekst 500 - onopgemaakt, zodat het een gewone serverfout lijkt
    (geen herkenbare 'nette' pagina die verraadt dat de toegang bewust geblokkeerd is)."""
    return "Internal Server Error", 500, {"Content-Type": "text/plain; charset=utf-8"}


def _toegang_pad(config) -> Path:
    return Path(config.state_path).parent / "toegang.json"


def _laad_toegang(config) -> dict:
    try:
        with open(_toegang_pad(config), encoding="utf-8") as bestand:
            data = json.load(bestand)
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("buiten_werking", [])
    data.setdefault("pogingen", {})
    return data


def _schrijf_toegang(config, data: dict) -> None:
    pad = _toegang_pad(config)
    pad.parent.mkdir(parents=True, exist_ok=True)
    with open(pad, "w", encoding="utf-8") as bestand:
        json.dump(data, bestand, ensure_ascii=False, indent=2)


def _is_buiten_werking(config, gebruiker: str) -> bool:
    return bool(gebruiker) and gebruiker in set(_laad_toegang(config).get("buiten_werking", []))


def _registreer_geblokkeerde_poging(config, gebruiker: str, wachtwoord_klopte: bool,
                                    ip: str | None, user_agent: str | None) -> None:
    """Telt (en verrijkt) een inlogpoging van een buiten-werking-gezet account, zodat
    je op de beheerpagina ziet dát en hoe vaak ze het blijven proberen."""
    data = _laad_toegang(config)
    pogingen = data.setdefault("pogingen", {})
    record = pogingen.setdefault(gebruiker, {
        "aantal": 0, "eerste": None, "laatste": None,
        "laatste_ip": None, "laatste_user_agent": None, "laatste_wachtwoord_klopte": None,
    })
    nu = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record["aantal"] = int(record.get("aantal", 0)) + 1
    record["eerste"] = record.get("eerste") or nu
    record["laatste"] = nu
    record["laatste_ip"] = ip
    record["laatste_user_agent"] = user_agent
    record["laatste_wachtwoord_klopte"] = wachtwoord_klopte
    _schrijf_toegang(config, data)


# --- Gebruikers-logboek (alleen zichtbaar voor beheerders) --------------------
# Een stil logboek per account (logboek.json naast state.json): hoe vaak iemand
# inlogt, hoeveel tijd hij op de site doorbrengt, welke pagina's hij bezoekt en
# welke woningen hij het meest bekijkt/doorrekent. Wordt gevoed door een
# before_request-hook (zie create_app) en is uitsluitend in te zien op de
# beheerpagina /gebruikers. Bewust "stil": normale gebruikers merken hier niets
# van. We bewaren alleen tellingen (geen volledige klik-geschiedenis), zodat het
# bestand klein blijft. Schrijven gaat via een lock zodat gelijktijdige requests
# binnen één worker elkaars telling niet overschrijven.
_LOGBOEK_LOCK = threading.Lock()

# Endpoints die als "paginabezoek" meetellen, met hun leesbare label. API-, poll-
# en actie-endpoints staan hier bewust niet in (die zouden de telling vervuilen).
_PAGINA_LABELS = {
    "kaart": "Kaart",
    "berekening": "Berekening",
    "wwso": "WWSO-punten",
    "data_analyse": "Data-analyse",
    "reken_instellingen": "Reken-instellingen",
    "handmatig_toevoegen": "Toevoegen",
    "verwijderd": "Verwijderd",
    "toegangsbeheer": "Toegangsbeheer",
}
# Endpoints die we volledig negeren (statics, polling, in/uitloggen en de
# beheerpagina's zelf) - die zeggen niets over echt gebruik.
_ACTIVITEIT_NEGEREN = {
    None, "static", "login", "logout", "handmatig_status", "gebruikers",
}
# GET-endpoints waarbij het bekijken van een specifieke woning telt.
_WONING_BEKEKEN_ENDPOINTS = {"berekening", "wwso"}
# POST-endpoints waarbij een woning daadwerkelijk (opnieuw) is doorgerekend.
_WONING_BEREKEND_ENDPOINTS = {"berekening_opslaan", "wwso_bereken"}
# Gat tussen twee acties dat nog als "aaneengesloten bezig" telt (30 min); daarna
# nemen we aan dat de gebruiker weg was en tellen we de pauze niet mee.
_IDLE_DREMPEL_SECONDEN = 30 * 60


def _logboek_pad(config) -> Path:
    return Path(config.state_path).parent / "logboek.json"


def _laad_logboek(config) -> dict:
    try:
        with open(_logboek_pad(config), encoding="utf-8") as bestand:
            data = json.load(bestand)
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("gebruikers", {})
    return data


def _schrijf_logboek(config, data: dict) -> None:
    pad = _logboek_pad(config)
    pad.parent.mkdir(parents=True, exist_ok=True)
    with open(pad, "w", encoding="utf-8") as bestand:
        json.dump(data, bestand, ensure_ascii=False, indent=2)


def _logboek_record(data: dict, gebruiker: str) -> dict:
    return data["gebruikers"].setdefault(gebruiker, {
        "logins": 0, "eerste_login": None, "laatste_login": None,
        "laatste_activiteit": None, "totaal_seconden": 0,
        "paginas": {}, "woningen_bekeken": {}, "woningen_berekend": {},
        "_laatste_ts": None,
    })


def _registreer_login(config, gebruiker: str) -> None:
    """Telt een geslaagde login. Zet _laatste_ts opnieuw, zodat de pauze sinds de
    vorige sessie niet als 'tijd op de site' wordt meegerekend."""
    if not gebruiker:
        return
    try:
        with _LOGBOEK_LOCK:
            data = _laad_logboek(config)
            rec = _logboek_record(data, gebruiker)
            nu = datetime.now(timezone.utc).isoformat(timespec="seconds")
            rec["logins"] = int(rec.get("logins", 0)) + 1
            rec["eerste_login"] = rec.get("eerste_login") or nu
            rec["laatste_login"] = nu
            rec["laatste_activiteit"] = nu
            rec["_laatste_ts"] = nu
            _schrijf_logboek(config, data)
    except Exception:
        # Loggen mag de site nooit stukmaken.
        pass


def _registreer_activiteit(config, gebruiker: str, endpoint: str | None,
                           view_args: dict | None, method: str) -> None:
    """Werkt het stille logboek bij voor één request: tijd-op-site (som van gaten
    onder de idle-drempel), paginatelling en per-woning bekeken/berekend."""
    if not gebruiker or endpoint in _ACTIVITEIT_NEGEREN:
        return
    try:
        with _LOGBOEK_LOCK:
            data = _laad_logboek(config)
            rec = _logboek_record(data, gebruiker)
            nu = datetime.now(timezone.utc)

            vorig = rec.get("_laatste_ts")
            if vorig:
                try:
                    gat = (nu - datetime.fromisoformat(vorig)).total_seconds()
                    if 0 < gat <= _IDLE_DREMPEL_SECONDEN:
                        rec["totaal_seconden"] = int(rec.get("totaal_seconden", 0)) + int(gat)
                except ValueError:
                    pass
            rec["_laatste_ts"] = nu.isoformat(timespec="seconds")
            rec["laatste_activiteit"] = nu.isoformat(timespec="seconds")

            label = _PAGINA_LABELS.get(endpoint)
            if label:
                paginas = rec.setdefault("paginas", {})
                paginas[label] = int(paginas.get(label, 0)) + 1

            object_id = (view_args or {}).get("object_id")
            if object_id and method == "GET" and endpoint in _WONING_BEKEKEN_ENDPOINTS:
                w = rec.setdefault("woningen_bekeken", {})
                w[object_id] = int(w.get(object_id, 0)) + 1
            if object_id and method == "POST" and endpoint in _WONING_BEREKEND_ENDPOINTS:
                w = rec.setdefault("woningen_berekend", {})
                w[object_id] = int(w.get(object_id, 0)) + 1

            _schrijf_logboek(config, data)
    except Exception:
        pass


def _format_duur(seconden) -> str:
    try:
        seconden = int(seconden)
    except (TypeError, ValueError):
        return "0 min"
    if seconden < 60:
        return f"{seconden} sec"
    minuten, _ = divmod(seconden, 60)
    uren, minuten = divmod(minuten, 60)
    if uren:
        return f"{uren} u {minuten} min"
    return f"{minuten} min"


def _format_tijdstip(iso) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d-%m-%Y %H:%M")
    except (TypeError, ValueError):
        return str(iso)


def _laad_reken_defaults(config) -> dict:
    """Globaal ingestelde standaardwaarden (reken_defaults.json). Leeg = nog nooit
    iets globaal aangepast, dan gelden de RekenUitgangspunten-constanten."""
    try:
        data = json.loads(_reken_defaults_pad(config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _schrijf_reken_defaults(config, defaults: dict) -> None:
    pad = _reken_defaults_pad(config)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(defaults, indent=2, ensure_ascii=False), encoding="utf-8")


def _ongeveer_gelijk(a, b) -> bool:
    """Float-veilige gelijkheid: een pand 'volgde' de oude globale waarde als zijn
    opgeslagen waarde daar (vrijwel) aan gelijk is."""
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b


def _effectieve_globale_defaults(config) -> dict:
    """De gedeelde uitgangspunten: de RekenUitgangspunten-standaard, overschreven
    door wat er globaal is ingesteld (reken_defaults.json). Alleen de gedeelde velden
    (dus zonder koopsom/aantal_kamers). Percentages als fractie."""
    # koopsom/aantal_kamers zijn verplichte velden maar irrelevant voor de gedeelde
    # standaarden; dummy 0 om de overige defaults uit te lezen.
    basis = asdict(RekenUitgangspunten(koopsom=0, aantal_kamers=0))
    globaal = _laad_reken_defaults(config)
    return {key: globaal.get(key, basis[key]) for key in _GEDEELDE_REKENVELDEN}


def _reken_uitgangspunten_dict(item, globale_defaults: dict) -> dict:
    """Standaardaannames met de koopsom en het aantal kamers voorgevuld uit de woning
    zelf, en de gedeelde velden op de globaal ingestelde standaard. Fractie (0.08)."""
    uitg = asdict(RekenUitgangspunten(
        koopsom=float(item.prijs or 0),
        aantal_kamers=int(item.aantal_kamers_mogelijk or 0),
    ))
    for key, waarde in globale_defaults.items():
        if key in uitg:
            uitg[key] = waarde
    return uitg


def _huidige_uitgangspunten(item, config, globale_defaults: dict | None = None) -> dict:
    """De voor déze woning geldende uitgangspunten: globale standaard + voorvulling,
    overschreven door wat de gebruiker eerder op de rekenpagina heeft aangepast.
    `globale_defaults` kan worden meegegeven om per-item herlezen van reken_defaults.json
    te vermijden (bv. bij de kaart-lijst met veel woningen)."""
    if globale_defaults is None:
        globale_defaults = _effectieve_globale_defaults(config)
    uitg = _reken_uitgangspunten_dict(item, globale_defaults)
    for key, waarde in (item.berekening or {}).items():
        if key in uitg:
            uitg[key] = waarde
    # De oppervlakte voor de ICR vóór ophoging komt uit de woning zelf (advertentie-m²,
    # niet de BAG-oppervlakte) - geen bewerkbaar rekenveld. Na de overrides gezet zodat
    # 'ie altijd de actuele advertentie-m² weergeeft en niet een oude opgeslagen waarde.
    uitg["oppervlakte_m2"] = float(item.oppervlakte_advertentie or item.primaire_oppervlakte or 0)
    return uitg


def _live_totalen(item, config, globale_defaults: dict | None = None):
    """De investeerder-onafhankelijke totalen (winst p/m, eigen inleg ná ophoging,
    schakelgeld vóór ophoging) doorgerekend met dezelfde uitgangspunten als de
    rekenpagina, zodat de kaart/lijst altijd overeenkomen met de rekentool - ook als
    je de globale uitgangspunten aanpast. (None, None, None) als er geen koopsom of
    aantal kamers is. De totalen gebruiken aantal_investeerders = 1; de kaart deelt
    zelf door het gekozen aantal investeerders."""
    uitg = _huidige_uitgangspunten(item, config, globale_defaults)
    if not uitg.get("koopsom") or not uitg.get("aantal_kamers"):
        return None, None, None
    uitg = dict(uitg)
    uitg["aantal_investeerders"] = 1
    r = bereken_rekentool(RekenUitgangspunten(**uitg))
    return r.winst_pm_pp, r.eigen_inleg_na_ophoging_pp, r.eigen_inleg_voor_ophoging_totaal


def _velden_voor_weergave(uitg: dict, alleen_gedeeld: bool = False) -> list[dict]:
    velden = []
    for key, label, soort in REKENVELDEN:
        if alleen_gedeeld and key not in _GEDEELDE_REKENVELDEN:
            continue
        waarde = uitg[key]
        if soort == "procent":
            waarde = round(waarde * 100, 4)
        # Hele getallen zonder ".0" tonen (bv. 550 i.p.v. 550.0) - schoner invulveld.
        if isinstance(waarde, float) and waarde.is_integer():
            waarde = int(waarde)
        velden.append({"key": key, "label": label, "soort": soort, "waarde": waarde})
    return velden


def _laad_steenhub_users(pad: str) -> dict:
    """Leest de users.json van de steenhub.nl-app (read-only ingekoppeld, zie
    deploy/docker-compose.yml). Elke gebruiker heeft daar een 'wachtwoord_hash'
    (werkzeug). Ontbreekt/onleesbaar het bestand, dan gewoon geen steenhub-logins."""
    try:
        with open(pad, encoding="utf-8") as bestand:
            data = json.load(bestand)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _steenhub_login_beschikbaar(config: Config) -> bool:
    if not config.steenhub_users_file:
        return False
    users = _laad_steenhub_users(config.steenhub_users_file)
    return any(isinstance(a, dict) and a.get("wachtwoord_hash") for a in users.values())


# Een geldige (maar betekenisloze) hash; hiertegen checken we bij een onbekende
# steenhub-gebruiker, zodat zo'n poging evenveel tijd kost als bij een bestaande.
_DUMMY_HASH = generate_password_hash("dummy")


def _kloppend_wachtwoord(config: Config, gebruiker: str, wachtwoord: str) -> bool:
    # 1) Eigen KANSEN_APP_USERS (los wachtwoord per gebruiker uit de env).
    verwacht = config.kansen_app_users.get(gebruiker)
    if verwacht is not None and hmac.compare_digest(verwacht, wachtwoord):
        # Tijdsveilig vergelijken (hmac.compare_digest) i.p.v. == , zodat de
        # responstijd niets verraadt over hoeveel tekens van het wachtwoord kloppen.
        return True
    # 2) Zelfde accounts als steenhub.nl (users.json met werkzeug-hashes), zodat je
    # met je steenhub-login ook op de kaart-website kunt. Elke poging leest het
    # bestand opnieuw, zodat een nieuwe steenhub-gebruiker meteen werkt zonder de
    # kansen-container te herstarten.
    if config.steenhub_users_file:
        account = _laad_steenhub_users(config.steenhub_users_file).get(gebruiker)
        hash_waarde = account["wachtwoord_hash"] if (
            isinstance(account, dict) and account.get("wachtwoord_hash")
        ) else _DUMMY_HASH
        # Altijd een hash-check doen (ook tegen de dummy-hash bij een onbekende
        # gebruiker), zodat de reactietijd niet verraadt of de gebruikersnaam
        # bestaat (timing-enumeratie).
        geldig = check_password_hash(hash_waarde, wachtwoord)
        return bool(isinstance(account, dict) and account.get("wachtwoord_hash") and geldig)
    return False


def _listing_naar_json(item, config, globale_defaults: dict | None = None) -> dict:
    # Winst/inleg/schakelgeld live doorrekenen met de actuele (globale + per-woning)
    # uitgangspunten, zodat de kaart en lijst overeenkomen met de rekentool.
    winst_totaal, inleg_na_totaal, schakelgeld_totaal = _live_totalen(item, config, globale_defaults)
    return {
        "object_id": item.object_id,
        "url": item.url,
        "weergavenaam": item.weergavenaam,
        "wijknaam": item.wijknaam,
        "lat": item.lat,
        "lon": item.lon,
        "prijs": item.prijs,
        "prijs_per_m2": item.prijs_per_m2,
        "primaire_oppervlakte": item.primaire_oppervlakte,
        "bag_oppervlakte": item.bag_oppervlakte,
        "oppervlakte_advertentie": item.oppervlakte_advertentie,
        "aantal_kamers_mogelijk": item.aantal_kamers_mogelijk,
        "aantal_kamers_handmatig": item.aantal_kamers_handmatig,
        # p.p.-velden (legacy) afgeleid van de totalen bij het standaardaantal
        # investeerders; de kaart/lijst rekenen zelf met de _totaal-velden hieronder.
        "winst_pm_pp": None if winst_totaal is None else winst_totaal / AANTAL_INVESTEERDERS,
        "eigen_inleg_pp": None if inleg_na_totaal is None else inleg_na_totaal / AANTAL_INVESTEERDERS,
        # Investeerder-onafhankelijke totalen (aantal_investeerders = 1), zodat de
        # kaart zelf kan omrekenen naar 1/2/3 investeerders. Live doorgerekend met de
        # actuele uitgangspunten, dus altijd gelijk aan de rekentool.
        "winst_pm_totaal": winst_totaal,
        "eigen_inleg_na_ophoging_totaal": inleg_na_totaal,
        "schakelgeld_totaal": schakelgeld_totaal,
        "opslag_percentage": item.opslag_percentage,
        "huurprijsopslag_signalen": item.huurprijsopslag_signalen,
        "stad": item.stad,
        "check_signalen": item.check_signalen,
        "woz_check_nodig": item.woz_check_nodig,
        "woz_check_url": item.woz_check_url,
        "opmerking": item.opmerking,
        "eerst_gezien": item.eerst_gezien,
        "laatst_gezien": item.laatst_gezien,
        "laatst_beschikbaar": item.laatst_beschikbaar,
        "laatst_gecheckt": item.laatst_gecheckt,
        "status": item.status,
        "favoriet": item.favoriet,
        "bekendmaking_waarschuwingen": item.bekendmaking_waarschuwingen,
        "bronnen": item.bronnen,
        # Zoeklink op adres: fallback voor woningen die (nog) alleen via de NVM/Move-
        # bron binnenkwamen en dus geen directe Funda-link hebben. Funda's eigen
        # zoekpagina werkt slecht/blokkeert; een Google-zoekopdracht op het adres +
        # "funda" zet de advertentie meestal bovenaan (in twee klikken bij de ad).
        "zoek_url": "https://www.google.com/search?q=" + quote_plus(((item.weergavenaam or "") + " funda").strip()),
    }


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__)
    # Achter Caddy (reverse proxy) staat request.remote_addr anders op het interne
    # Docker-IP van Caddy i.p.v. het echte bezoekers-IP, en is request.is_secure
    # altijd False (Caddy termineert https en praat http naar binnen). x_for=1 /
    # x_proto=1 vertrouwt precies één hop, zodat het echte IP (inlog-throttle,
    # logboek) en het echte schema (Secure-cookie, HSTS) kloppen.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    if config is None:
        config = load_config()

    if not config.kansen_app_users and not _steenhub_login_beschikbaar(config):
        raise SystemExit(
            "Geen inlogbron: KANSEN_APP_USERS is leeg én er is geen bruikbaar STEENHUB_USERS_FILE "
            "(users.json van steenhub.nl). Vul minstens 1 gebruiker:wachtwoord-paar in KANSEN_APP_USERS "
            "in (zie .env.example) of koppel de steenhub-users.json in, anders zou de kaart zonder "
            "wachtwoord open staan."
        )
    if not config.kansen_app_secret_key:
        raise SystemExit("KANSEN_APP_SECRET_KEY ontbreekt - vul een willekeurige, geheime waarde in.")

    app.secret_key = config.kansen_app_secret_key

    # Veilige sessiecookie-instellingen (onzichtbaar voor de gebruiker).
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    # Inlog-throttle per client-IP (losse, testbare logica in throttle.py).
    inlog_throttle = LoginThrottle()

    @app.before_request
    def _cookie_secure_bij_https():
        # SECURE (cookie alleen over https) per request op basis van het echte
        # schema: aan achter Caddy (https via X-Forwarded-Proto), uit bij http
        # (tests/lokaal) zodat de werkzeug-testclient de cookie niet wegfiltert.
        app.config["SESSION_COOKIE_SECURE"] = request.is_secure

    @app.after_request
    def _beveiligingsheaders(response: Response) -> Response:
        """Standaard beveiligingsheaders; onzichtbaar voor de gebruiker."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    # Wie het toegangsbeheer mag bedienen. KANSEN_APP_BEHEERDERS (env) heeft
    # voorrang; anders de eigen env-accounts (KANSEN_APP_USERS) plus de vaste
    # eigenaar hieronder, zodat de eigenaar ook als hij met zijn steenhub-account
    # inlogt de beheerpagina ziet. De meelezende collega's horen hier niet bij.
    beheerders = set(config.kansen_app_beheerders) or (
        set(config.kansen_app_users) | _STANDAARD_BEHEERDERS
    )

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            gebruiker = session.get("gebruiker")
            if not gebruiker:
                return redirect(url_for("login", next=request.path))
            # Account tussentijds buiten werking gezet? Meteen "storing" tonen en de
            # sessie leegmaken, zodat de omzetting direct effect heeft (niet pas bij
            # de volgende login) en het net een technische storing lijkt.
            if _is_buiten_werking(config, gebruiker):
                session.pop("gebruiker", None)
                return _storing_respons()
            return view(*args, **kwargs)

        return wrapped

    def beheerder_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("gebruiker") not in beheerders:
                abort(404)  # 404 i.p.v. 403: niet-beheerders merken niet dat de pagina bestaat.
            return view(*args, **kwargs)

        return wrapped

    @app.before_request
    def _log_gebruikersactiviteit():
        # Stil logboek bijwerken voor ingelogde gebruikers (zie _registreer_activiteit).
        # Nooit iets teruggeven: dit mag de request-afhandeling niet beïnvloeden.
        gebruiker = session.get("gebruiker")
        if gebruiker:
            _registreer_activiteit(
                config, gebruiker, request.endpoint, request.view_args, request.method,
            )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        fout = None
        if request.method == "POST":
            ip = request.remote_addr or "onbekend"
            if inlog_throttle.geblokkeerd(ip):
                fout = "Te veel mislukte inlogpogingen. Wacht een paar minuten en probeer het opnieuw."
                return render_template("login.html", fout=fout), 429
            gebruiker = request.form.get("gebruiker", "").strip()
            wachtwoord = request.form.get("wachtwoord", "")
            klopt = _kloppend_wachtwoord(config, gebruiker, wachtwoord)
            # Buiten werking gezet account: registreer de poging (ook bij een fout
            # wachtwoord, zodat je ziet hoe vaak ze het proberen) en toon een neutrale
            # storingspagina - nooit inloggen, nooit "geen toegang" verklappen.
            if _is_buiten_werking(config, gebruiker):
                _registreer_geblokkeerde_poging(
                    config, gebruiker, klopt,
                    request.remote_addr, request.headers.get("User-Agent"),
                )
                return _storing_respons()
            if klopt:
                inlog_throttle.wis(ip)
                session["gebruiker"] = gebruiker
                _registreer_login(config, gebruiker)
                return redirect(request.args.get("next") or url_for("kaart"))
            inlog_throttle.registreer_mislukt(ip)
            fout = "Onjuiste gebruikersnaam of wachtwoord."
        return render_template("login.html", fout=fout)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.pop("gebruiker", None)
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def kaart():
        return render_template(
            "kaart.html", gebruiker=session["gebruiker"],
            is_beheerder=session["gebruiker"] in beheerders,
        )

    @app.route("/api/kansen")
    @login_required
    def api_kansen():
        state = StateStore(config.state_path)
        # Favorieten blijven op de kaart staan, ook als de woning inmiddels van
        # Funda is (afgevallen) - zodat een eventuele vergunning-waarschuwing bij
        # het pand zichtbaar blijft en je 'm niet kwijtraakt zodra je gekocht hebt.
        zichtbaar = [
            item
            for item in state.all()
            if (item.status == "actief" or item.favoriet)
            and item.lat is not None
            and item.lon is not None
        ]
        globale = _effectieve_globale_defaults(config)  # één keer lezen, niet per woning
        return jsonify([_listing_naar_json(item, config, globale) for item in zichtbaar])

    @app.route("/api/broninfo")
    @login_required
    def api_broninfo():
        # Telling per databron (Funda / NVM): hoeveel woningen elk kanaal levert,
        # hoeveel overlappen en hoeveel maar via één van de twee binnenkomen.
        state = StateStore(config.state_path)
        return jsonify(bron_statistieken(state.all()))

    @app.route("/ververs", methods=["POST"])
    @login_required
    def ververs():
        # Mail-gebaseerde scan (alleen nieuwe woningen sinds gisteren) - een
        # handmatige "Ververs nu" laat 'm meteen draaien i.p.v. te wachten op
        # de volgende geplande scan.
        result = pipeline.run(config)
        return jsonify({
            "nieuw_actief": len(result.nieuw_actief),
            "nieuw_afgevallen": len(result.nieuw_afgevallen),
            "fouten": result.fouten,
        })

    @app.route("/kansen/<object_id>/favoriet", methods=["POST"])
    @login_required
    def kans_favoriet(object_id):
        # Zet het sterretje aan/uit. Alleen favorieten worden gemonitord op nieuwe
        # kamerverhuurvergunningen binnen 50 m (zie bekendmakingen.py); de check
        # zelf loopt mee op de dagelijkse scan of via "Vergunningen checken".
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            return jsonify({"fout": "Onbekende woning."}), 404
        item.favoriet = not item.favoriet
        state.upsert(item)
        state.save()
        return jsonify({"favoriet": item.favoriet})

    @app.route("/bekendmakingen/check", methods=["POST"])
    @login_required
    def bekendmakingen_check():
        # Handmatige "check nu": draait alleen de favoriet-vergunningcheck (geen
        # Funda-scan) en mailt bij nieuwe treffers.
        samenvatting = pipeline.controleer_bekendmakingen(config)
        return jsonify(samenvatting)

    def _vergunningen_index_pad() -> Path:
        return Path(config.state_path).parent / "vergunningen_index.json"

    @app.route("/api/vergunningen")
    @login_required
    def api_vergunningen():
        # Alle bruikbare kamerverhuurvergunningen uit de index (gevuld door de
        # 'vergunningen-index'-service). Voedt zowel de "Toon vergunningen"-
        # kaartlaag als het data-analyse-dashboard; het dashboard rekent zelf de
        # aggregaten uit deze lijst (klein genoeg, en zo blijven de filters
        # 'afgelopen X dagen' / per wijk interactief zonder extra server-calls).
        index = vergunningenindex.VergunningIndex(_vergunningen_index_pad())
        vergunningen = [
            {
                "publicatie_id": v.get("publicatie_id"),
                "adres": v.get("adres"),
                # Teruggebracht naar één van de 14 officiële Rotterdamse gebieden,
                # zodat de per-wijk-analyse niet uiteenvalt in tientallen buurten.
                "gebied": vergunningenindex.normaliseer_gebied(v.get("gebied")),
                "postcode": v.get("postcode"),
                "aantal_personen": v.get("aantal_personen"),
                # regulier vs. overgangsbepaling (legalisatie bestaande situatie) -
                # None zolang een record nog niet is her-geclassificeerd.
                "soort": v.get("soort"),
                "datum": v.get("datum"),
                "besluitdatum": v.get("besluitdatum"),
                "zaaknummer": v.get("zaaknummer"),
                "url": v.get("url"),
                "lat": v.get("lat"),
                "lon": v.get("lon"),
            }
            for v in index.bruikbare()
        ]
        return jsonify({
            "vergunningen": vergunningen,
            "bijgewerkt": index.meta.get("bijgewerkt"),
            "compleet": index.meta.get("volledige_enumeratie_gedaan", False)
            and not index.onverwerkt(),
        })

    # --- Test-adressen (handmatig, voor het testen van de 50m-afstandseis) ---
    # Een los adres (niet per se te koop) op de kaart met een groene 50m-cirkel
    # eromheen, om te zien wat binnen de kamerverhuurvergunning-afstand valt. Alleen
    # voor beheerders; opgeslagen als simpele JSON naast de state (gedeeld, want het
    # is een persoonlijk hulpmiddel van de eigenaar - geen kansen-/vergunningdata).
    def _test_adressen_pad() -> Path:
        return Path(config.state_path).parent / "test_adressen.json"

    def _laad_test_adressen() -> list:
        pad = _test_adressen_pad()
        if not pad.exists():
            return []
        try:
            data = json.loads(pad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _schrijf_test_adressen(lijst: list) -> None:
        _test_adressen_pad().write_text(
            json.dumps(lijst, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @app.route("/api/test-adressen")
    @beheerder_required
    def api_test_adressen():
        return jsonify({"adressen": _laad_test_adressen()})

    @app.route("/api/test-adressen", methods=["POST"])
    @beheerder_required
    def api_test_adres_toevoegen():
        data = request.get_json(silent=True) or {}
        adres = (data.get("adres") or "").strip()
        if not adres:
            return jsonify({"fout": "Geen adres opgegeven."}), 400
        try:
            resultaat = geocode.geocode_vrij_landelijk(adres)
        except geocode.GeocodeError:
            return jsonify({"fout": f"Adres niet gevonden: '{adres}'. Vul het volledig in (bv. 'Pompstraat 42, Rotterdam')."}), 400
        except Exception:
            return jsonify({"fout": "Adres opzoeken mislukt (PDOK niet bereikbaar). Probeer het nog eens."}), 502
        if resultaat.lat is None or resultaat.lon is None:
            return jsonify({"fout": "Geen coördinaat gevonden voor dit adres."}), 400
        nieuw = {
            "id": resultaat.adresseerbaarobject_id or resultaat.nummeraanduiding_id or uuid.uuid4().hex[:8],
            "weergavenaam": resultaat.weergavenaam,
            "lat": resultaat.lat,
            "lon": resultaat.lon,
            "toegevoegd": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        lijst = _laad_test_adressen()
        if not any(a.get("id") == nieuw["id"] for a in lijst):
            lijst.append(nieuw)
            _schrijf_test_adressen(lijst)
        return jsonify({"adres": nieuw})

    @app.route("/api/test-adressen/<adres_id>/verwijderen", methods=["POST"])
    @beheerder_required
    def api_test_adres_verwijderen(adres_id):
        lijst = _laad_test_adressen()
        overig = [a for a in lijst if a.get("id") != adres_id]
        _schrijf_test_adressen(overig)
        return jsonify({"ok": True, "verwijderd": len(lijst) - len(overig)})

    # --- Concurrentie-scan (trechter binnen 50 m rond een adres) ---
    # Telt hoeveel woningen binnen 50 m - volgens de regels - theoretisch nog in
    # aanmerking komen voor een 4+-kamerverhuurvergunning: adressen ophalen,
    # opkoopbescherming (WOZ), 50 m-norm (officiele kaart), en als vermelding de
    # BAG-oppervlakte + of ze recent te koop stonden (eigen archief). De scan duurt
    # even (veel losse API-calls), draait op de achtergrond en mailt het resultaat naar
    # de opgegeven ontvanger(s). Beheerder-only.
    @app.route("/opkoop-scan", methods=["POST"])
    @beheerder_required
    def opkoop_scan_starten():
        data = request.get_json(silent=True) or {}
        adres = (data.get("adres") or "").strip()
        if not adres:
            return jsonify({"fout": "Geen adres opgegeven."}), 400

        # Ontvanger(s): komma-gescheiden, zelf te kiezen (geen vaste BCC meer). Leeg
        # veld valt terug op het geconfigureerde report-adres.
        ontvangers_ruw = (data.get("ontvangers") or "").strip()
        if ontvangers_ruw:
            kandidaten = [a.strip() for a in ontvangers_ruw.split(",") if a.strip()]
            ontvangers = [a for a in kandidaten if _EMAIL_RE.match(a)]
            ongeldig = [a for a in kandidaten if not _EMAIL_RE.match(a)]
            if ongeldig:
                return jsonify({"fout": "Ongeldig e-mailadres: " + ", ".join(ongeldig)}), 400
        else:
            ontvangers = list(config.report_to)
        if not ontvangers:
            return jsonify({"fout": "Geen (geldig) ontvanger-adres opgegeven."}), 400

        try:
            res = geocode.geocode_vrij_landelijk(adres)
        except geocode.GeocodeError:
            return jsonify({"fout": f"Adres niet gevonden: '{adres}'. Vul het volledig in (bv. 'Pompstraat 42, Rotterdam')."}), 400
        except Exception:
            return jsonify({"fout": "Adres opzoeken mislukt (PDOK niet bereikbaar). Probeer het nog eens."}), 502
        if res.lat is None or res.lon is None:
            return jsonify({"fout": "Geen coördinaat gevonden voor dit adres."}), 400

        grens = int(config.opkoopbescherming_woz_grens)
        centrum, lat, lon = res.weergavenaam, res.lat, res.lon

        # #5: matchen tegen het blijvende listings-archief (te-koop-geweest). Lukt het
        # laden niet, of is het archief nog leeg, dan draait de scan gewoon zonder #5.
        te_koop_func = None
        try:
            arch = archief.ListingArchief(archief.archief_pad_voor(config.state_path))
            if len(arch):
                index = arch.index_op_adres()

                def te_koop_func(weergavenaam, grens_datum):  # noqa: E731 - kleine closure
                    rec = index.get(archief.normaliseer_adres(weergavenaam))
                    if rec is None:
                        return None
                    peil = rec.laatste_peildatum()
                    return peil if peil >= grens_datum else None
        except Exception:
            app.logger.exception("Kon listings-archief niet laden voor de concurrentie-scan")

        def _foutmail(exc):
            try:
                send_mail(
                    config,
                    f"Concurrentie-scan MISLUKT voor {centrum}",
                    f"<p>De scan voor <b>{centrum}</b> is vastgelopen met een fout:</p>"
                    f"<pre>{type(exc).__name__}: {exc}</pre>"
                    "<p>Probeer het later opnieuw; blijft het misgaan, dan is er iets mis "
                    "met PDOK, de WOZ-dienst, BAG, de vergunningenkaart of de mailverzending.</p>",
                    f"De scan voor {centrum} is vastgelopen met een fout:\n\n"
                    f"{type(exc).__name__}: {exc}\n\n"
                    "Probeer het later opnieuw.",
                    recipients=ontvangers, stille_bcc=False,
                )
            except Exception:
                app.logger.exception("Kon ook de foutmail niet versturen voor %s", centrum)

        bestandsnaam = "concurrentie-scan-" + (re.sub(r"[^A-Za-z0-9]+", "-", centrum).strip("-").lower() or "rapport") + ".pdf"

        def _werk():
            try:
                resultaat = opkoop_scan.scan(lat, lon, grens, centrum, te_koop_func=te_koop_func)
                onderwerp, html_body, text_body = opkoop_scan.bouw_cover(resultaat)
                pdf_bytes = opkoop_rapport_pdf.bouw_rapport_pdf(resultaat)
                send_mail(config, onderwerp, html_body, text_body,
                          recipients=ontvangers, stille_bcc=False,
                          attachments=[(bestandsnaam, pdf_bytes, "pdf")])
                app.logger.info("Concurrentie-scan %s: %d adressen -> pool %d "
                                "(woz_onbereikbaar=%s, gis_onbereikbaar=%s); mail naar %s",
                                centrum, len(resultaat.rijen), len(resultaat.pool),
                                resultaat.woz_onbereikbaar, resultaat.gis_onbereikbaar,
                                ", ".join(ontvangers))
            except Exception as exc:
                # Nooit stil falen: ook bij een fout krijgt de gebruiker een mail.
                app.logger.exception("Concurrentie-scan mislukt voor %s", centrum)
                _foutmail(exc)

        threading.Thread(target=_werk, daemon=True).start()
        return jsonify({"ok": True,
                        "melding": f"Scan gestart voor {centrum} (50 m-straal). "
                                   f"Het resultaat wordt gemaild naar {', '.join(ontvangers)}."})

    @app.route("/data-analyse")
    @login_required
    def data_analyse():
        return render_template("data_analyse.html", gebruiker=session["gebruiker"])

    @app.route("/kansen/<object_id>/verwijderen", methods=["POST"])
    @login_required
    def kans_verwijderen(object_id):
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            return jsonify({"fout": "Onbekende woning."}), 404
        reden = request.form.get("reden", "").strip() or "Handmatig verwijderd via kansen.steenhub.nl."
        item.status = "afgevallen"
        item.handmatig_verwijderd = True
        item.afvalreden = reden
        state.upsert(item)
        state.save()
        return jsonify({"ok": True})

    @app.route("/kansen/<object_id>/kamers", methods=["POST"])
    @login_required
    def kans_kamers_aanpassen(object_id):
        # Laat de gebruiker het aantal kamers per woning handmatig corrigeren (de
        # 18m2-vuistregel klopt in de praktijk niet altijd, bv. bij een ongunstige
        # plattegrond) - winst/eigen inleg worden meteen met dat aantal herberekend.
        # Leeg veld = terug naar de automatisch berekende waarde.
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            return jsonify({"fout": "Onbekende woning."}), 404

        ruwe_waarde = request.form.get("aantal_kamers", "").strip()
        if ruwe_waarde == "":
            item.aantal_kamers_handmatig = False
            oppervlakte = item.primaire_oppervlakte
            if item.stad == "den_haag":
                item.aantal_kamers_mogelijk = den_haag.bereken_max_bewoners(oppervlakte) if oppervlakte else None
            else:
                item.aantal_kamers_mogelijk = bereken_aantal_kamers_mogelijk(oppervlakte) if oppervlakte else None
        else:
            try:
                aantal = int(ruwe_waarde)
            except ValueError:
                return jsonify({"fout": "Ongeldig aantal kamers."}), 400
            if aantal < 0:
                return jsonify({"fout": "Aantal kamers moet 0 of hoger zijn."}), 400
            item.aantal_kamers_mogelijk = aantal
            item.aantal_kamers_handmatig = True

        if item.prijs and item.aantal_kamers_mogelijk:
            investering = bereken_investering(
                item.aantal_kamers_mogelijk, item.prijs, item.opslag_percentage, m2=item.primaire_oppervlakte
            )
            item.winst_pm_pp = investering.winst_pm_pp if investering else None
            item.eigen_inleg_pp = investering.eigen_inleg_na_ophoging_pp if investering else None
            item.schakelgeld_totaal = investering.totale_zelf_in_te_leggen if investering else None
        else:
            item.winst_pm_pp = None
            item.eigen_inleg_pp = None
            item.schakelgeld_totaal = None

        state.upsert(item)
        state.save()
        return jsonify(_listing_naar_json(item, config))

    @app.route("/woning/<object_id>/berekening")
    @login_required
    def berekening(object_id):
        # Rekentool per woning: koopsom (vraagprijs) en aantal kamers voorgevuld,
        # alle uitgangspunten aanpasbaar; wat je invult wordt automatisch bij de
        # woning bewaard (zie berekening_opslaan) en de sommen rechts rollen er
        # meteen uit (zie static/berekening.js).
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            abort(404)
        uitg = _huidige_uitgangspunten(item, config)
        resultaat = bereken_rekentool(RekenUitgangspunten(**uitg))
        return render_template(
            "berekening.html", item=item, velden=_velden_voor_weergave(uitg),
            resultaat=asdict(resultaat), gebruiker=session["gebruiker"],
        )

    @app.route("/woning/<object_id>/berekening", methods=["POST"])
    @login_required
    def berekening_opslaan(object_id):
        # Auto-opslag vanaf de rekenpagina: neemt de ingevulde uitgangspunten over,
        # bewaart ze bij de woning en geeft de doorgerekende sommen terug als JSON.
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            return jsonify({"fout": "Onbekende woning."}), 404

        data = request.get_json(silent=True) or {}
        uitg = _huidige_uitgangspunten(item, config)
        for key, _label, soort in REKENVELDEN:
            if key not in data:
                continue
            ruw = str(data[key]).replace(",", ".").strip()
            if ruw == "":
                continue
            try:
                waarde = float(ruw)
            except ValueError:
                return jsonify({"fout": f"Ongeldige waarde voor {key}."}), 400
            uitg[key] = waarde / 100 if soort == "procent" else waarde
        uitg["aantal_kamers"] = int(round(uitg["aantal_kamers"]))
        uitg["aantal_investeerders"] = int(round(uitg["aantal_investeerders"])) or 1

        item.berekening = uitg
        state.upsert(item)
        state.save()
        resultaat = bereken_rekentool(RekenUitgangspunten(**uitg))
        return jsonify(asdict(resultaat))

    @app.route("/woning/<object_id>/berekening.pdf")
    @login_required
    def berekening_pdf(object_id):
        # Downloadbare PDF met exact dezelfde uitgangspunten en resultaten als de
        # rekenpagina (op basis van de opgeslagen waarden bij de woning).
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            abort(404)
        uitg = _huidige_uitgangspunten(item, config)
        resultaat = bereken_rekentool(RekenUitgangspunten(**uitg))
        from kansen_site import rapport_pdf  # lazy: reportlab niet nodig voor de rest van de site
        pdf = rapport_pdf.bouw_berekening_pdf(
            item, _velden_voor_weergave(uitg), asdict(resultaat), date.today(),
        )
        veilig = re.sub(r"[^A-Za-z0-9]+", "_", (item.weergavenaam or object_id)).strip("_") or "berekening"
        return Response(
            pdf, mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="berekening_{veilig}.pdf"'},
        )

    def _woning_uit_payload(data: dict) -> Woning:
        """Bouw een Woning (WWSO-invoer) uit de JSON van het rekenscherm. De UI
        werkt additief: elke kamer heeft zijn eigen (privé)elementen en er is een
        lijst gedeelde elementen. `type` bepaalt het effect (zie WWSO_ELEMENTEN)."""
        def f(x, standaard=0.0):
            try:
                return float(str(x).replace(",", ".").strip())
            except (TypeError, ValueError):
                return standaard

        def i(x, standaard=0):
            try:
                return int(round(float(str(x).replace(",", ".").strip())))
            except (TypeError, ValueError):
                return standaard

        def _keuken(el) -> Keuken | None:
            if f(el.get("aanrecht_m")) <= 0:
                return None
            return Keuken(
                aanrecht_m=f(el.get("aanrecht_m")),
                voorzieningen=[v for v in (el.get("voorzieningen") or [])
                               if v in KEUKEN_VOORZIENINGEN],
                extra_kastruimte_60cm=i(el.get("extra_kastruimte_60cm")),
            )

        kamers = []
        for k in (data.get("kamers") or []):
            if f(k.get("oppervlakte_m2")) <= 0:
                continue
            kamer = Kamer(oppervlakte_m2=f(k.get("oppervlakte_m2")),
                          verwarmd=bool(k.get("verwarmd", True)))
            for el in (k.get("elementen") or []):
                spec = WWSO_ELEMENTEN.get(el.get("type"))
                if not spec:
                    continue
                effect = spec["effect"]
                if effect == "keuken":
                    kamer.keuken = _keuken(el)
                elif effect == "sanitair":
                    kamer.eigen_sanitair.append(spec["key"])
                elif effect == "buitenruimte":
                    kamer.eigen_buitenruimte_m2 += f(el.get("oppervlakte_m2"))
                elif effect in ("overige", "vertrek"):
                    kamer.eigen_overige_m2 += f(el.get("oppervlakte_m2"))
            kamers.append(kamer)

        gedeelde_ruimten = []
        for el in (data.get("gedeelde_elementen") or []):
            spec = WWSO_ELEMENTEN.get(el.get("type"))
            if not spec:
                continue
            toegang = i(el.get("aantal_kamers_toegang")) or None
            adressen = max(1, i(el.get("aantal_adressen"), 1))
            effect = spec["effect"]
            if effect == "keuken":
                keuken = _keuken(el)
                if keuken:
                    gedeelde_ruimten.append(GedeeldeRuimte(
                        soort="keuken", keuken=keuken, aantal_kamers_toegang=toegang))
            elif effect == "sanitair":
                gedeelde_ruimten.append(GedeeldeRuimte(
                    soort="sanitair", sanitair=[spec["key"]],
                    aantal_kamers_toegang=toegang))
            elif effect == "verkeer":
                gedeelde_ruimten.append(GedeeldeRuimte(
                    soort="verkeer", verwarmd=bool(el.get("verwarmd")),
                    aantal_adressen=adressen, aantal_kamers_toegang=toegang))
            elif effect in ("vertrek", "overige", "buitenruimte"):
                if f(el.get("oppervlakte_m2")) > 0:
                    gedeelde_ruimten.append(GedeeldeRuimte(
                        soort=effect, oppervlakte_m2=f(el.get("oppervlakte_m2")),
                        verwarmd=bool(el.get("verwarmd")),
                        aantal_adressen=adressen, aantal_kamers_toegang=toegang))

        label = (data.get("energielabel") or "").strip().upper() or None
        if label not in ENERGIELABEL_PUNTEN:
            label = None
        return Woning(
            kamers=kamers,
            energielabel=label,
            bouwjaar=i(data.get("bouwjaar")) or None,
            woz_waarde=f(data.get("woz_waarde")) or None,
            woz_oppervlakte_m2=f(data.get("woz_oppervlakte_m2")) or None,
            corop_gemiddelde_woz_m2=(f(data.get("corop_gemiddelde_woz_m2"))
                                     or COROP_GROOT_RIJNMOND_WOZ_M2),
            gedeelde_ruimten=gedeelde_ruimten,
        )

    @app.route("/woning/<object_id>/wwso")
    @login_required
    def wwso(object_id):
        # WWSO-rekentool: schat per kamer de maximale kale huur (punten -> euro,
        # Huurcommissie-beleidsboek onzelfstandige woonruimte). De uitkomst kan met
        # één klik als "kale huur per kamer" in de investerings-rekentool worden gezet.
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            abort(404)
        aantal_kamers = item.aantal_kamers_mogelijk or 1
        totaal_m2 = item.primaire_oppervlakte or 0
        kamer_m2 = round(totaal_m2 / aantal_kamers, 1) if aantal_kamers else 0
        prive_palet = {k: v for k, v in WWSO_ELEMENTEN.items()
                       if v["context"] in ("prive", "beide")}
        gedeeld_palet = {k: v for k, v in WWSO_ELEMENTEN.items()
                         if v["context"] in ("gedeeld", "beide")}
        return render_template(
            "wwso.html",
            item=item,
            gebruiker=session["gebruiker"],
            aantal_kamers=aantal_kamers,
            kamer_m2=kamer_m2,
            energielabels=list(ENERGIELABEL_PUNTEN.keys()),
            keuken_voorzieningen=KEUKEN_VOORZIENING_LABELS,
            elementen=WWSO_ELEMENTEN,
            prive_palet=prive_palet,
            gedeeld_palet=gedeeld_palet,
            corop_woz_m2=COROP_GROOT_RIJNMOND_WOZ_M2,
        )

    @app.route("/woning/<object_id>/wwso/bereken", methods=["POST"])
    @login_required
    def wwso_bereken(object_id):
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            return jsonify({"fout": "Onbekende woning."}), 404
        data = request.get_json(silent=True) or {}
        woning = _woning_uit_payload(data)
        if not woning.kamers:
            return jsonify({"fout": "Vul minstens één kamer met oppervlakte in."}), 400
        resultaten = bereken_woning(woning)
        kamers = [
            {
                "oppervlakte_m2": r.kamer.oppervlakte_m2,
                "punten_per_rubriek": r.punten_per_rubriek,
                "totaal_punten": r.totaal_punten,
                "max_kale_huur": round(r.max_kale_huur, 2),
            }
            for r in resultaten
        ]
        huren = [r.max_kale_huur for r in resultaten]
        return jsonify({
            "kamers": kamers,
            "gemiddelde_huur": round(sum(huren) / len(huren), 2),
            "laagste_huur": round(min(huren), 2),
            "totaal_huur": round(sum(huren), 2),
        })

    @app.route("/woning/<object_id>/wwso/gebruik", methods=["POST"])
    @login_required
    def wwso_gebruik(object_id):
        # Zet de gekozen (gemiddelde) WWSO-huur als "kale huur per kamer" in de
        # investerings-rekentool van deze woning en spring daarheen.
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            return jsonify({"fout": "Onbekende woning."}), 404
        data = request.get_json(silent=True) or {}
        try:
            huur = float(str(data.get("kale_huur_per_kamer")).replace(",", ".").strip())
        except (TypeError, ValueError):
            return jsonify({"fout": "Ongeldige huurwaarde."}), 400
        if huur <= 0:
            return jsonify({"fout": "Ongeldige huurwaarde."}), 400
        uitg = _huidige_uitgangspunten(item, config)
        uitg["kale_huur_per_kamer"] = round(huur, 2)
        item.berekening = uitg
        state.upsert(item)
        state.save()
        return jsonify({"ok": True, "url": url_for("berekening", object_id=object_id)})

    @app.route("/reken-instellingen", methods=["GET", "POST"])
    @login_required
    def reken_instellingen():
        # Globale standaard-uitgangspunten voor de rekentool van álle panden. Wijzig
        # je hier bv. de rente, dan geldt dat voor elk pand dat de oude globale waarde
        # volgde; een pand waar je bewust iets anders invulde blijft ongemoeid.
        state = StateStore(config.state_path)
        oud = _effectieve_globale_defaults(config)

        if request.method == "POST":
            nieuw = dict(oud)
            for key, _label, soort in REKENVELDEN:
                if key not in _GEDEELDE_REKENVELDEN or key not in request.form:
                    continue
                ruw = request.form.get(key, "").replace(",", ".").strip()
                if ruw == "":
                    continue
                try:
                    waarde = float(ruw)
                except ValueError:
                    flash(f"Ongeldige waarde voor {key} - overgeslagen.")
                    continue
                nieuw[key] = waarde / 100 if soort == "procent" else waarde
            nieuw["aantal_investeerders"] = int(round(nieuw["aantal_investeerders"])) or 1

            # Propageer elke gewijzigde waarde naar de panden die de óude globale
            # waarde volgden (of er geen eigen waarde voor hadden). Panden met een
            # afwijkende (bewust ingevulde) waarde blijven ongewijzigd.
            gewijzigd = [k for k in _GEDEELDE_REKENVELDEN if not _ongeveer_gelijk(nieuw[k], oud[k])]
            bijgewerkt = 0
            if gewijzigd:
                for woning in state.all():
                    ber = woning.berekening
                    if not ber:
                        continue  # geen eigen berekening -> volgt de globale vanzelf
                    pand_gewijzigd = False
                    for k in gewijzigd:
                        if k in ber and _ongeveer_gelijk(ber[k], oud[k]):
                            ber[k] = nieuw[k]
                            pand_gewijzigd = True
                    if pand_gewijzigd:
                        woning.berekening = ber
                        state.upsert(woning)
                        bijgewerkt += 1
                if bijgewerkt:
                    state.save()

            _schrijf_reken_defaults(config, {k: nieuw[k] for k in _GEDEELDE_REKENVELDEN})
            flash(
                f"Standaardwaarden opgeslagen. {bijgewerkt} pand(en) volgden de oude waarde "
                "en zijn meebijgewerkt; panden met een eigen waarde bleven ongewijzigd."
            )
            return redirect(url_for("reken_instellingen"))

        return render_template(
            "reken_instellingen.html",
            velden=_velden_voor_weergave(dict(oud), alleen_gedeeld=True),
            gebruiker=session["gebruiker"],
        )

    @app.route("/kansen/<object_id>/terugplaatsen", methods=["POST"])
    @login_required
    def kans_terugplaatsen(object_id):
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            return jsonify({"fout": "Onbekende woning."}), 404
        item.status = "actief"
        item.handmatig_verwijderd = False
        item.afvalreden = None
        state.upsert(item)
        state.save()
        flash(f"{item.weergavenaam} teruggeplaatst.")
        return redirect(url_for("verwijderd"))

    @app.route("/verwijderd")
    @login_required
    def verwijderd():
        state = StateStore(config.state_path)
        items = sorted(
            (item for item in state.all() if item.handmatig_verwijderd),
            key=lambda item: item.laatst_gezien, reverse=True,
        )
        return render_template("verwijderd.html", items=items, gebruiker=session["gebruiker"])

    @app.route("/handmatig-toevoegen", methods=["GET", "POST"])
    @login_required
    def handmatig_toevoegen():
        # Voor achterstanden/gebieden die de mail-alert niet dekt: plak een
        # lijst adressen ("POSTCODE HUISNUMMER [funda-link]", één per regel)
        # of een ruwe kopieer-plak van een Funda-resultatenpagina - zelfde
        # parser (rotterdam_scanner/handmatig.py) en dezelfde checks als het
        # bestaande CLI-script handmatig_toevoegen.py, nu ook vanaf de
        # website bereikbaar.
        if request.method == "POST":
            tekst = request.form.get("tekst", "")
            forceer_herprocessen = request.form.get("forceer_herprocessen") == "on"
            listings, parse_fouten = parse_bestand(tekst)

            lopend = _lees_handmatige_run(config)
            if lopend and lopend.get("status") == "bezig":
                flash("Er loopt al een verwerking - even wachten tot die klaar is.")
                return redirect(url_for("handmatig_toevoegen"))
            if not listings:
                flash("Geen enkel adres kon uit de geplakte tekst gelezen worden.")
                return redirect(url_for("handmatig_toevoegen"))

            # Op de achtergrond draaien: een grote batch (geocoding + checks) duurt te
            # lang voor één request - die zou door de gebruiker of een server-time-out
            # worden afgebroken, en de state wordt pas aan het eind opgeslagen. Nu start
            # de verwerking in een aparte thread en wordt de uitkomst weggeschreven, zodat
            # je het tabblad mag sluiten en de bevestiging er staat als je terugkomt.
            gestart = datetime.now(timezone.utc).isoformat(timespec="seconds")
            gebruiker = session["gebruiker"]  # vastleggen: in de thread is er geen sessie
            _schrijf_handmatige_run(config, {
                "status": "bezig", "gestart": gestart,
                "aangeleverd": len(listings), "gebruiker": gebruiker,
            })

            def _draai():
                try:
                    run_result = pipeline.run_handmatig(
                        config, listings, forceer_herprocessen=forceer_herprocessen,
                    )
                    _schrijf_handmatige_run(config, {
                        "status": "klaar", "gestart": gestart,
                        "klaar": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "gebruiker": gebruiker,
                        "resultaat": {
                            "aangeleverd": len(listings),
                            "nieuw_actief": len(run_result.nieuw_actief),
                            "nieuw_afgevallen": len(run_result.nieuw_afgevallen),
                            "nieuw_onbekend_adres": len(run_result.nieuw_onbekend_adres),
                            "al_bekend": len(run_result.al_bekend),
                            "fouten": parse_fouten + run_result.fouten,
                        },
                    })
                except Exception as exc:  # noqa: BLE001 - alles vangen zodat de status niet op "bezig" blijft hangen
                    _schrijf_handmatige_run(config, {
                        "status": "fout", "gestart": gestart,
                        "klaar": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "gebruiker": gebruiker, "aangeleverd": len(listings),
                        "fout": str(exc), "parse_fouten": parse_fouten,
                    })

            threading.Thread(target=_draai, daemon=True).start()
            flash(
                f"Verwerking van {len(listings)} adres(sen) gestart. Je kunt dit tabblad "
                "sluiten - de uitkomst verschijnt hier zodra het klaar is."
            )
            return redirect(url_for("handmatig_toevoegen"))

        return render_template(
            "handmatig_toevoegen.html",
            laatste=_lees_handmatige_run(config), gebruiker=session["gebruiker"],
        )

    @app.route("/handmatig-toevoegen/status")
    @login_required
    def handmatig_status():
        # De pagina pollt dit om "bezig -> klaar" live te tonen, ook na terugkomst.
        return jsonify(_lees_handmatige_run(config) or {"status": "leeg"})

    @app.route("/toegangsbeheer", methods=["GET", "POST"])
    @beheerder_required
    def toegangsbeheer():
        # Beheerpagina: vink een account "buiten werking" aan (dan ziet het bij het
        # inloggen enkel een storingspagina) en zie hoe vaak zo'n account het tóch
        # nog probeert. Beheerders kunnen nooit zichzelf/elkaar buitensluiten.
        data = _laad_toegang(config)
        if request.method == "POST":
            aangevinkt = set(request.form.getlist("buiten_werking"))
            data["buiten_werking"] = sorted(n for n in aangevinkt if n not in beheerders)
            _schrijf_toegang(config, data)
            flash("Toegangsinstellingen opgeslagen.")
            return redirect(url_for("toegangsbeheer"))

        geblokkeerd = set(data.get("buiten_werking", []))
        pogingen = data.get("pogingen", {})
        # Alle bekende accounts: eigen env-accounts + steenhub-collega's + al eerder
        # geblokkeerde namen (die eventueel niet meer in een bron voorkomen).
        namen = set(config.kansen_app_users) | geblokkeerd
        if config.steenhub_users_file:
            namen |= set(_laad_steenhub_users(config.steenhub_users_file))
        accounts = [
            {
                "naam": naam,
                "beheerder": naam in beheerders,
                "buiten_werking": naam in geblokkeerd,
                "poging": pogingen.get(naam),
            }
            for naam in sorted(namen)
        ]
        return render_template(
            "toegangsbeheer.html", accounts=accounts, gebruiker=session["gebruiker"],
        )

    @app.route("/mail-voorkeuren", methods=["GET", "POST"])
    @login_required
    def mail_voorkeuren_pagina():
        # Per account: eigen mailadres + per mailing aan/uit. Bepaalt wie welke mail
        # ontvangt (i.p.v. de vaste REPORT_TO-lijst uit de env).
        gebruiker = session["gebruiker"]
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            actief = set(request.form.getlist("mailings"))
            if email and not mail_voorkeuren.emails_geldig(email):
                flash("Vul geldige e-mailadres(sen) in, meerdere gescheiden door een komma "
                      "(of laat het leeg om geen mail te ontvangen).")
            else:
                oud = mail_voorkeuren.voorkeuren_voor(config, gebruiker)
                was_nieuw = not oud.get("email")
                mail_voorkeuren.zet_voorkeuren(config, gebruiker, email, actief)
                try:
                    # Bevestigingsmail naar de gebruiker; mag het opslaan nooit laten
                    # mislukken, dus fouten (bv. SMTP down) bewust negeren.
                    mail_voorkeuren.stuur_voorkeur_bevestiging(
                        config, email, actief, nieuw=was_nieuw)
                except Exception:
                    pass
                flash("Mailvoorkeuren opgeslagen.")
                return redirect(url_for("mail_voorkeuren_pagina"))
            # bij fout: toon de ingevulde waarden terug
            huidig = {"email": email, **{k: (k in actief) for k in mail_voorkeuren.MAILING_KEYS}}
        else:
            huidig = mail_voorkeuren.voorkeuren_voor(config, gebruiker)

        mailings = [
            {"key": k, "naam": naam, "uitleg": uitleg, "aan": bool(huidig.get(k))}
            for k, naam, uitleg in mail_voorkeuren.MAILINGS
        ]
        return render_template(
            "mail_voorkeuren.html", email=huidig.get("email", ""), mailings=mailings,
            gebruiker=gebruiker,
        )

    @app.route("/rente-historie")
    @login_required
    def rente_historie():
        # Grafiek van de vaste Domivest-cel (80% LTV, 5 jaar vast) door de tijd heen.
        # backfill zorgt dat de handmatig bijgehouden startpunten er staan, ook vóór
        # de eerste dagelijkse run.
        try:
            rente_update.backfill_historie(config)
        except Exception:
            pass
        punten = rente_update.laad_historie(config)
        return render_template(
            "rente_historie.html", punten=punten, gebruiker=session["gebruiker"],
        )

    @app.route("/gebruikers")
    @beheerder_required
    def gebruikers():
        # Stil logboek per account (alleen voor beheerders): logins, tijd op de site,
        # meest bezochte pagina's en meest bekeken/doorgerekende woningen.
        data = _laad_logboek(config)
        state = StateStore(config.state_path)

        def _woningnaam(object_id: str) -> str:
            item = state.get(object_id)
            return item.weergavenaam if item is not None else object_id

        def _top(teller: dict, n: int = 8) -> list[dict]:
            gesorteerd = sorted(teller.items(), key=lambda kv: (-kv[1], kv[0]))
            return [
                {"naam": _woningnaam(oid), "object_id": oid, "aantal": aantal}
                for oid, aantal in gesorteerd[:n]
            ]

        gebruikers_lijst = []
        for naam, rec in data.get("gebruikers", {}).items():
            paginas = sorted(
                rec.get("paginas", {}).items(), key=lambda kv: (-kv[1], kv[0])
            )
            gebruikers_lijst.append({
                "naam": naam,
                "beheerder": naam in beheerders,
                "logins": rec.get("logins", 0),
                "tijd": _format_duur(rec.get("totaal_seconden", 0)),
                "eerste_login": _format_tijdstip(rec.get("eerste_login")),
                "laatste_activiteit": _format_tijdstip(rec.get("laatste_activiteit")),
                "paginas": [{"label": l, "aantal": a} for l, a in paginas],
                "bekeken": _top(rec.get("woningen_bekeken", {})),
                "berekend": _top(rec.get("woningen_berekend", {})),
            })
        # Actiefste bovenaan (meeste tijd), daarna op naam.
        gebruikers_lijst.sort(
            key=lambda g: (-int(data["gebruikers"][g["naam"]].get("totaal_seconden", 0)), g["naam"])
        )
        return render_template(
            "gebruikers.html", gebruikers=gebruikers_lijst, gebruiker=session["gebruiker"],
        )

    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5001)
