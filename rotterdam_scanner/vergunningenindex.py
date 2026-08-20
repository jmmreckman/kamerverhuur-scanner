"""Volledige index van verleende kamerverhuurvergunningen in Rotterdam.

Waar rotterdam_scanner/bekendmakingen.py alleen de recente vergunningen bij je
favorieten checkt, bouwt deze module de héle geschiedenis op als doorzoekbare
dataset voor de kaart-website: een aparte "Toon vergunningen"-kaartlaag en een
data-analyse-dashboard (hoeveel vergunningen per wijk, per week/maand, trend over
de jaren).

Bron is dezelfde officiële KOOP-zoekdienst (SRU). Per vergunning halen we de
gestructureerde tekst van de bekendmaking op (via repository.overheid.nl, dat
stabieler is dan de zoek.officielebekendmakingen.nl-spiegel) en lezen daar
Gebied (wijk), adres, postcode, "aan N personen" (aantal bewoners),
verzenddatum besluit en zaaknummer uit.

De opbouw is incrementeel en resumable (scripts/vergunningen_index_bijwerken.py):
één keer worden alle publicatie-id's geïnventariseerd (stubs), daarna wordt elke
run een begrensde batch bekendmakingen opgehaald + geparsed + gegeocodeerd, tot
het archief compleet is. Daarna hoeven alleen nieuwe vergunningen erbij.
"""
from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from .bekendmakingen import SRU_URL, _NS
from .geocode import GeocodeError, geocode_vrij

logger = logging.getLogger(__name__)

# Rotterdam publiceert de per-adres kamerverhuurvergunningen sinds ~2022 onder de
# titel "Vergunning kamerverhuur <adres>". We doorzoeken beide termen; oudere jaren
# leveren simpelweg weinig/geen per-adres treffers op (toen was er nog geen
# gestructureerde per-adres publicatie).
_CREATOR = "Rotterdam"
_ZOEKTERMEN = ("kamerverhuur", "kamerbewoning")

_GZD = "{http://standaarden.overheid.nl/sru}"

# Titels die zeker geen per-adres verleende vergunning zijn (beleidsregels,
# verordeningen, aanvragen/ontwerpen, intrekkingen/weigeringen, en de bulk-
# overgangsvergunningen voor bestaande situaties). Goedkope voorfilter vóór we een
# body ophalen; de body-parse is daarna de uiteindelijke toets (die eist dat de
# tekst een verleende vergunning mét adres is).
_UITSLUIT_RE = re.compile(
    r"intrekking|ingetrokken|weiger|geweigerd|buiten behandeling|beleidsregel|"
    r"verordening|nadere regels|aanvraag|aangevraag|aanvragen|overgangsbepaling|"
    r"ontwerp",
    re.IGNORECASE,
)
# Kandidaat zodra "kamerverhuur" of "kamerbewoning" ergens in de titel staat -
# bewust ruim, want het titelformat verschilt per jaar ("Vergunning kamerverhuur
# X", "Verleende vergunning kamerbewoning X", of kaal "kamerverhuur X"). De
# body-parse filtert de niet-per-adres-treffers er daarna uit.
_KANDIDAAT_RE = re.compile(r"kamer(?:verhuur|bewoning)", re.IGNORECASE)

# Ophogen zodra de enumeratie-filter (_KANDIDAAT_RE/_UITSLUIT_RE) of parse_body
# wijzigt: dan doet werk_bij één keer een volledige her-inventarisatie van het
# archief én probeert het eerder mislukte parses opnieuw met de nieuwe parser.
# v2 = verbreed naar de oudere formats (2019-2021). v3 = adres uit de titel als
# terugval + losser "Gebied:" (dekt de per-adres 'bestaande situatie'-grants van 2021
# die in de body geen 'Adres:' hebben). Zie git-geschiedenis.
_ENUMERATIE_VERSIE = 3

_MAANDEN = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}
_NL_GETAL = {
    "een": 1, "één": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6,
    "zeven": 7, "acht": 8, "negen": 9, "tien": 10, "elf": 11, "twaalf": 12,
}


def _get(url: str, params: dict | None = None, pogingen: int = 3):
    """GET met een paar retries - de KOOP-proxy geeft af en toe een 502."""
    laatste = None
    for i in range(pogingen):
        if i:
            time.sleep(2 * i)
        try:
            resp = requests.get(url, params=params, timeout=40)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as exc:
            laatste = exc
    raise laatste


def _sru_page(query: str, start: int, aantal: int = 100) -> tuple[int, list[dict]]:
    params = {
        "operation": "searchRetrieve", "version": "2.0", "x-connection": "BEK",
        "query": query, "maximumRecords": str(aantal), "startRecord": str(start),
        "recordSchema": "gzd",
    }
    root = ET.fromstring(_get(SRU_URL, params=params).text)
    totaal_el = root.find("sru:numberOfRecords", _NS)
    totaal = int(totaal_el.text) if totaal_el is not None and totaal_el.text else 0

    records = []
    for rec in root.iter(_GZD + "gzd"):
        titel = rec.find(".//dcterms:title", _NS)
        datum = rec.find(".//dcterms:date", _NS)
        pref = rec.find(".//gzd:preferredUrl", _NS)
        if titel is None or not titel.text:
            continue
        html_url = None
        for item in rec.iter(_GZD + "itemUrl"):
            if item.get("manifestation") == "html" and item.text:
                html_url = item.text
        records.append({
            "titel": titel.text,
            "datum": datum.text if datum is not None and datum.text else "",
            "url": pref.text if pref is not None and pref.text else "",
            "html_url": html_url,
        })
    return totaal, records


def _pub_id(url: str) -> str:
    naam = (url or "").rstrip("/").rsplit("/", 1)[-1]
    return naam[:-5] if naam.endswith(".html") else naam


def enumereer_stubs(vanaf: date | None = None):
    """Alle per-adres kamerverhuur-publicatie-id's van Rotterdam (metadata: titel,
    publicatiedatum, html-url). `vanaf` beperkt tot recente publicaties (voor de
    dagelijkse bijwerking); zonder `vanaf` het hele archief (eenmalige inventaris)."""
    stubs: dict[str, dict] = {}
    for term in _ZOEKTERMEN:
        query = f"(cql.textAndIndexes={term}) and (dt.creator={_CREATOR})"
        if vanaf is not None:
            query += f" and (dt.date>={vanaf.isoformat()})"
        start = 1
        totaal = None
        while True:
            try:
                totaal, records = _sru_page(query, start)
            except Exception as exc:  # noqa: BLE001
                logger.warning("SRU-enumeratie mislukt (%s, start=%s): %s", term, start, exc)
                break
            if not records:
                break
            for rec in records:
                if not _KANDIDAAT_RE.search(rec["titel"]) or _UITSLUIT_RE.search(rec["titel"]):
                    continue
                pid = _pub_id(rec["url"] or rec["html_url"] or "")
                if pid:
                    stubs.setdefault(pid, {
                        "publicatie_id": pid,
                        "titel": rec["titel"],
                        "datum": rec["datum"],
                        "url": rec["url"],
                        "html_url": rec["html_url"],
                        "verwerkt": False,
                    })
            start += len(records)
            if totaal and start > totaal:
                break
    return stubs


def _tekst(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _nl_datum_naar_iso(tekst: str | None) -> str | None:
    if not tekst:
        return None
    match = re.match(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", tekst.strip(), re.IGNORECASE)
    if not match:
        return None
    dag, maandnaam, jaar = match.groups()
    maand = _MAANDEN.get(maandnaam.lower())
    if not maand:
        return None
    try:
        return date(int(jaar), maand, int(dag)).isoformat()
    except ValueError:
        return None


def _aantal_personen(tekst: str) -> int | None:
    # 2021+ gestructureerd: "aan 3 personen". 2019-2020 vrije tekst: "door maximaal
    # vier personen" (getal soms als woord).
    match = re.search(r"aan\s+(\d+)\s+persone?n", tekst, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:maximaal|door)\s+([0-9]+|[a-zéëï]+)\s+persone?n", tekst, re.IGNORECASE)
    if match:
        woord = match.group(1).lower()
        return int(woord) if woord.isdigit() else _NL_GETAL.get(woord)
    return None


def _besluitdatum(tekst: str) -> str | None:
    # 2022+: "Verzenddatum besluit: ...". 2021: "Datum besluit: ...". 2019-2020
    # vrije tekst: "op 20 mei 2019 de volgende vergunning heeft verleend".
    for patroon in (
        r"Verzenddatum besluit:\s*(\d{1,2}\s+\w+\s+\d{4})",
        r"Datum besluit:\s*(\d{1,2}\s+\w+\s+\d{4})",
        r"\bop\s+(\d{1,2}\s+\w+\s+\d{4})\b[^.]{0,80}verleend",
    ):
        match = re.search(patroon, tekst, re.IGNORECASE)
        if match:
            iso = _nl_datum_naar_iso(match.group(1))
            if iso:
                return iso
    return None


# Adres uit de titel halen: "(Verleende) vergunning (voor) kamer(verhuur|bewoning)
# <adres>" of het kale "kamerverhuur <adres>" (2019). Terugval voor bekendmakingen
# die het adres alleen in de titel zetten - o.a. de per-adres "bestaande situatie
# onder de overgangsbepaling"-grants uit 2021, die in de body wél een "Gebied:" maar
# géén "Adres:" hebben.
_TITEL_ADRES_RE = re.compile(
    r"^\s*(?:verleende?\s+)?(?:vergunning\s+)?(?:voor\s+)?kamer(?:verhuur|bewoning)\s+(?P<adres>.+?)\s*$",
    re.IGNORECASE,
)
_TITEL_SUFFIX_RE = re.compile(r"\s*[-–]\s*(rectificatie|correctie|herstel).*$", re.IGNORECASE)


def _adres_uit_titel(titel: str | None) -> str | None:
    if not titel:
        return None
    match = _TITEL_ADRES_RE.match(titel)
    if not match:
        return None
    adres = _TITEL_SUFFIX_RE.sub("", match.group("adres")).strip()
    # Geen echt adres (bv. de bulk "onder de overgangsbepaling ..."-titel) -> negeren.
    if not adres or adres.lower().startswith(("onder de", "aanvragen")):
        return None
    return adres


def parse_body(html: str, titel: str | None = None) -> dict | None:
    """Leest de velden uit de tekst van een kamerverhuurvergunning. Dekt het
    gestructureerde format (2021+: 'Gebied:/Adres:/Postcode:/... aan N personen'), de
    oudere vrije tekst (2019-2020: '... door maximaal vier personen voor de woning met
    adres X, 3028 BN Rotterdam/Delfshaven') én de per-adres 'bestaande situatie'-grants
    (2021) die in de body wél 'Gebied:' maar geen 'Adres:' hebben - daar komt het adres
    uit de meegegeven titel. Geeft None als het geen verleende per-adres vergunning
    blijkt (bv. een beleidsstuk of enkel een aanvraag)."""
    tekst = _tekst(html)
    if "verleend" not in tekst.lower():
        return None  # geen verleende vergunning (bv. aanvraag/ontwerp/beleid)

    def zoek(patroon: str) -> str | None:
        match = re.search(patroon, tekst, re.IGNORECASE)
        return match.group(1).strip() if match else None

    # "Gebied:" loopt door tot het volgende label - niet elk format heeft "Adres:"
    # er direct achter (soms "Datum besluit:"/"Dossiernummer:").
    gebied = zoek(r"Gebied:\s*(.*?)\s+(?:Adres|Postcode|Datum besluit|Verzenddatum|Dossiernummer|Zaaknummer|Activiteit):")
    adres = zoek(r"Adres:\s*(.*?)\s+Postcode:")
    postcode = zoek(r"Postcode:\s*(\d{4}\s*[A-Z]{2})")

    if not adres:
        # Vrije-tekst format: "... adres <straat nr>, <postcode> Rotterdam/<wijk>".
        vrij = re.search(
            r"adres\s+(.+?),\s*(\d{4}\s*[A-Z]{2})\s+Rotterdam(?:\s*[/-]\s*([\w'’.\- ]+?))?\s*[.\s]",
            tekst,
            re.IGNORECASE,
        )
        if vrij:
            adres = vrij.group(1).strip()
            postcode = postcode or vrij.group(2)
            gebied = gebied or (vrij.group(3).strip() if vrij.group(3) else None)

    if not adres:
        # Laatste terugval: het adres uit de titel (body noemt alleen "Gebied:").
        adres = _adres_uit_titel(titel)

    if not adres:
        return None

    return {
        "gebied": gebied,
        "adres": adres,
        "postcode": postcode.replace(" ", "") if postcode else None,
        "aantal_personen": _aantal_personen(tekst),
        "besluitdatum": _besluitdatum(tekst),
        "zaaknummer": zoek(r"Zaaknummer:\s*([\w./-]+)"),
    }


class VergunningIndex:
    """Laadt/bewaart de index (data/vergunningen_index.json)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.meta: dict = {}
        self.vergunningen: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.meta = data.get("meta", {})
        self.vergunningen = data.get("vergunningen", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"meta": self.meta, "vergunningen": self.vergunningen}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def bruikbare(self) -> list[dict]:
        return [v for v in self.vergunningen.values() if v.get("verwerkt") and v.get("bruikbaar")]

    def onverwerkt(self) -> list[dict]:
        return [v for v in self.vergunningen.values() if not v.get("verwerkt")]


def _verwerk_stub(stub: dict) -> None:
    """Haalt de body op, parseert de velden en geocodeert - mutatie in-place. Zet
    altijd verwerkt=True zodat een mislukte/niet-bruikbare publicatie niet elke run
    opnieuw geprobeerd wordt."""
    stub["verwerkt"] = True
    stub["bruikbaar"] = False
    html_url = stub.get("html_url")
    if not html_url:
        return
    try:
        html = _get(html_url).text
    except Exception as exc:  # noqa: BLE001
        logger.info("Body ophalen mislukt (%s): %s", stub["publicatie_id"], exc)
        stub["verwerkt"] = False  # netwerkfout: volgende run opnieuw proberen
        return

    velden = parse_body(html, stub.get("titel"))
    if velden is None:
        return

    stub.update(velden)
    stub["bruikbaar"] = True

    # Coördinaten voor de kaartlaag (best-effort). Postcode+adres via PDOK.
    try:
        geo = geocode_vrij(velden["adres"], "Rotterdam")
        stub["lat"], stub["lon"] = geo.lat, geo.lon
        # Alleen als de bekendmaking zelf geen "Gebied" noemde (zeldzaam) - en dan
        # het grovere CBS-wijkniveau, dat qua granulariteit aansluit bij het
        # gemeente-"Gebied" (bv. "Delfshaven"), niet het fijnere buurtniveau, zodat
        # de per-wijk-analyse consistent blijft.
        if not stub.get("gebied") and geo.cbs_wijknaam:
            stub["gebied"] = geo.cbs_wijknaam
    except GeocodeError:
        stub["lat"] = stub["lon"] = None
    except Exception as exc:  # noqa: BLE001
        logger.info("Geocoderen mislukt (%s): %s", stub["publicatie_id"], exc)
        stub["lat"] = stub["lon"] = None


def werk_bij(index_path: Path, batch: int = 200, vandaag: date | None = None) -> dict:
    """Werkt de index één stap bij: (1) eenmalig het hele archief inventariseren als
    stubs, (2) altijd recente publicaties toevoegen, (3) een begrensde batch nog niet
    opgehaalde bekendmakingen ophalen/parsen/geocoderen. Geeft voortgang terug."""
    vandaag = vandaag or date.today()
    index = VergunningIndex(index_path)

    if index.meta.get("enumeratie_versie") != _ENUMERATIE_VERSIE:
        # Eerste run, of het enumeratie-/parse-filter is gewijzigd: het hele archief
        # (opnieuw) inventariseren. Nieuwe titels worden als stub toegevoegd; eerder
        # als "niet bruikbaar" afgeschreven publicaties krijgen een herkansing met de
        # nieuwe parser (verwerkt terug op False). Bestaande, wél bruikbare records
        # blijven ongemoeid (setdefault overschrijft niet).
        logger.info("Volledige (her)inventarisatie van het archief (enumeratie-versie %s)...", _ENUMERATIE_VERSIE)
        for pid, stub in enumereer_stubs().items():
            index.vergunningen.setdefault(pid, stub)
        for stub in index.vergunningen.values():
            if stub.get("verwerkt") and not stub.get("bruikbaar"):
                stub["verwerkt"] = False
        index.meta["enumeratie_versie"] = _ENUMERATIE_VERSIE
        index.meta["volledige_enumeratie_gedaan"] = True
    else:
        # Dagelijkse bijwerking: alleen recente publicaties opzoeken.
        for pid, stub in enumereer_stubs(vanaf=vandaag - timedelta(days=120)).items():
            index.vergunningen.setdefault(pid, stub)

    onverwerkt = index.onverwerkt()
    for stub in onverwerkt[:batch]:
        _verwerk_stub(stub)

    index.meta["bijgewerkt"] = datetime.now().isoformat(timespec="seconds")
    index.save()

    resterend = len(index.onverwerkt())
    return {
        "totaal": len(index.vergunningen),
        "bruikbaar": len(index.bruikbare()),
        "verwerkt_deze_run": min(len(onverwerkt), batch),
        "resterend": resterend,
        "compleet": resterend == 0,
    }


# --- Analyse-helpers (ook client-side in het dashboard mogelijk, maar hier voor tests) ---


def _iso_maand(datum_iso: str) -> str | None:
    return datum_iso[:7] if datum_iso and len(datum_iso) >= 7 else None


# De 14 officiële Rotterdamse gebieden. De bekendmakingen noemen in "Gebied:" meestal
# al één hiervan (soms als "Gebied/Wijk", bv. "Centrum/Stadsdriehoek"), maar de
# geocode-fallback en enkele oudere teksten leveren fijnere CBS-wijknamen. Daarom
# brengen we elke waarde terug naar één van deze 14 (zie normaliseer_gebied), zodat
# de per-wijk-analyse niet uiteenvalt in tientallen losse buurten.
GEBIEDEN = [
    "Centrum", "Charlois", "Delfshaven", "Feijenoord", "Hillegersberg-Schiebroek",
    "Hoek van Holland", "Hoogvliet", "IJsselmonde", "Kralingen-Crooswijk", "Noord",
    "Overschie", "Pernis", "Prins Alexander", "Rozenburg",
]


def _gebied_sleutel(tekst: str) -> str:
    """Normaliseert een gebied-/wijknaam tot een vergelijkbare sleutel: kleine
    letters, alleen a-z/0-9, losse woorden met één spatie ('Kralingen-Crooswijk' ->
    'kralingen crooswijk', "'s-Gravenland" -> 's gravenland')."""
    return re.sub(r"[^a-z0-9]+", " ", tekst.lower()).strip()


_GEBIED_CANON = {_gebied_sleutel(g): g for g in GEBIEDEN}

# CBS-wijk/buurt -> officieel gebied. Alleen nodig voor waarden die geen gebiednaam
# zijn (geocode-fallback of "Gebied/Wijk"-tweede-deel). Niet uitputtend; onbekende
# waarden vallen op "Overig" (zie normaliseer_gebied) i.p.v. verkeerd gegokt.
_WIJK_NAAR_GEBIED = {_gebied_sleutel(w): g for w, g in {
    # Centrum
    "Stadsdriehoek": "Centrum", "Cool": "Centrum", "Oude Westen": "Centrum",
    "Nieuwe Werk": "Centrum", "Dijkzigt": "Centrum", "CS-kwartier": "Centrum",
    # Delfshaven
    "Bospolder": "Delfshaven", "Tussendijken": "Delfshaven", "Spangen": "Delfshaven",
    "Nieuwe Westen": "Delfshaven", "Middelland": "Delfshaven", "Oud-Mathenesse": "Delfshaven",
    "Witte Dorp": "Delfshaven", "Schiemond": "Delfshaven",
    # Noord
    "Agniesebuurt": "Noord", "Provenierswijk": "Noord", "Oude Noorden": "Noord",
    "Liskwartier": "Noord", "Bergpolder": "Noord", "Blijdorp": "Noord",
    "Blijdorpsepolder": "Noord",
    # Kralingen-Crooswijk
    "Rubroek": "Kralingen-Crooswijk", "Nieuw Crooswijk": "Kralingen-Crooswijk",
    "Oud Crooswijk": "Kralingen-Crooswijk", "Crooswijk": "Kralingen-Crooswijk",
    "Kralingen-West": "Kralingen-Crooswijk", "Kralingen-Oost": "Kralingen-Crooswijk",
    "Kralingen": "Kralingen-Crooswijk", "Kralingse Bos": "Kralingen-Crooswijk",
    "De Esch": "Kralingen-Crooswijk", "Struisenburg": "Kralingen-Crooswijk",
    # Feijenoord
    "Noordereiland": "Feijenoord", "Kop van Zuid": "Feijenoord",
    "Kop van Zuid-Entrepot": "Feijenoord", "Entrepot": "Feijenoord",
    "Afrikaanderwijk": "Feijenoord", "Bloemhof": "Feijenoord", "Hillesluis": "Feijenoord",
    "Vreewijk": "Feijenoord", "Katendrecht": "Feijenoord",
    # IJsselmonde
    "Oud-IJsselmonde": "IJsselmonde", "Lombardijen": "IJsselmonde",
    "Groot-IJsselmonde": "IJsselmonde", "Beverwaard": "IJsselmonde",
    "Reyeroord": "IJsselmonde", "Sportdorp": "IJsselmonde", "Hordijkerveld": "IJsselmonde",
    # Charlois
    "Tarwewijk": "Charlois", "Carnisse": "Charlois", "Zuidwijk": "Charlois",
    "Pendrecht": "Charlois", "Zuidplein": "Charlois", "Wielewaal": "Charlois",
    "Heijplaat": "Charlois", "Oud-Charlois": "Charlois", "Charlois Zuidrand": "Charlois",
    # Prins Alexander
    "Het Lage Land": "Prins Alexander", "Lage Land": "Prins Alexander",
    "Prinsenland": "Prins Alexander", "'s-Gravenland": "Prins Alexander",
    "Zevenkamp": "Prins Alexander", "Ommoord": "Prins Alexander",
    "Oosterflank": "Prins Alexander", "Nesselande": "Prins Alexander",
    "Kralingseveer": "Prins Alexander",
    # Hillegersberg-Schiebroek
    "Schiebroek": "Hillegersberg-Schiebroek", "Hillegersberg-Zuid": "Hillegersberg-Schiebroek",
    "Hillegersberg-Noord": "Hillegersberg-Schiebroek", "Hillegersberg": "Hillegersberg-Schiebroek",
    "Terbregge": "Hillegersberg-Schiebroek", "Molenlaankwartier": "Hillegersberg-Schiebroek",
    "110-Morgen": "Hillegersberg-Schiebroek",
    # Overschie
    "Kleinpolder": "Overschie", "Zestienhoven": "Overschie", "Noord-Kethel": "Overschie",
    "Schieveen": "Overschie",
    # Hoogvliet
    "Hoogvliet-Noord": "Hoogvliet", "Hoogvliet-Zuid": "Hoogvliet",
}.items()}


def normaliseer_gebied(waarde) -> str:
    """Brengt een gebied-/wijkwaarde terug naar één van de 14 officiële gebieden.
    Verwerkt "Gebied/Wijk"-combinaties (neemt het gebied), losse wijknamen (via de
    map hierboven) en spelling-/koppeltekenvarianten. Onbekend -> "Overig"; leeg ->
    "Onbekend"."""
    if not waarde or not str(waarde).strip():
        return "Onbekend"
    delen = [d for d in str(waarde).split("/") if d.strip()]
    for deel in delen:
        canon = _GEBIED_CANON.get(_gebied_sleutel(deel))
        if canon:
            return canon
    for deel in delen:
        gebied = _WIJK_NAAR_GEBIED.get(_gebied_sleutel(deel))
        if gebied:
            return gebied
    return "Overig"


def analyse(vergunningen: list[dict], vandaag: date | None = None, dagen: int | None = None) -> dict:
    """Aggregaten voor het dashboard: aantal per wijk, per maand, per jaar en het
    totaal - optioneel beperkt tot de laatste `dagen`."""
    vandaag = vandaag or date.today()
    if dagen is not None:
        grens = (vandaag - timedelta(days=dagen)).isoformat()
        vergunningen = [v for v in vergunningen if (v.get("datum") or "") >= grens]

    per_wijk: dict[str, int] = {}
    per_maand: dict[str, int] = {}
    per_jaar: dict[str, int] = {}
    for v in vergunningen:
        wijk = v.get("gebied") or "Onbekend"
        per_wijk[wijk] = per_wijk.get(wijk, 0) + 1
        maand = _iso_maand(v.get("datum") or "")
        if maand:
            per_maand[maand] = per_maand.get(maand, 0) + 1
            per_jaar[maand[:4]] = per_jaar.get(maand[:4], 0) + 1

    return {
        "totaal": len(vergunningen),
        "per_wijk": dict(sorted(per_wijk.items(), key=lambda kv: kv[1], reverse=True)),
        "per_maand": dict(sorted(per_maand.items())),
        "per_jaar": dict(sorted(per_jaar.items())),
    }
