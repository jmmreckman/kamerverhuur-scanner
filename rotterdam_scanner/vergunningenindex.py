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
# verordeningen, intrekkingen/weigeringen, aanvragen, en de bulk-overgangs-
# vergunningen voor bestaande situaties). Goedkope voorfilter vóór we een body
# ophalen; de body-parse is daarna de uiteindelijke toets.
_UITSLUIT_RE = re.compile(
    r"intrekking|ingetrokken|weiger|geweigerd|buiten behandeling|beleidsregel|"
    r"verordening|nadere regels|aanvraag|aanvragen|overgangsbepaling",
    re.IGNORECASE,
)
_PER_ADRES_RE = re.compile(r"^\s*vergunning\s+kamer(?:verhuur|bewoning)\s+\S", re.IGNORECASE)

_MAANDEN = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
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
                if _UITSLUIT_RE.search(rec["titel"]) or not _PER_ADRES_RE.match(rec["titel"]):
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


def parse_body(html: str) -> dict | None:
    """Leest de gestructureerde velden uit de tekst van een kamerverhuurvergunning.
    Geeft None als het geen bruikbare per-adres vergunning blijkt (bv. toch een
    beleidsstuk zonder Gebied/Adres)."""
    tekst = _tekst(html)

    def zoek(patroon: str) -> str | None:
        match = re.search(patroon, tekst, re.IGNORECASE)
        return match.group(1).strip() if match else None

    gebied = zoek(r"Gebied:\s*(.*?)\s+Adres:")
    adres = zoek(r"Adres:\s*(.*?)\s+Postcode:")
    postcode = zoek(r"Postcode:\s*(\d{4}\s*[A-Z]{2})")
    personen_ruw = zoek(r"aan\s+(\d+)\s+persone?n")
    besluit = _nl_datum_naar_iso(zoek(r"Verzenddatum besluit:\s*(\d{1,2}\s+\w+\s+\d{4})"))
    zaaknummer = zoek(r"Zaaknummer:\s*([\w./-]+)")

    if not adres or not gebied:
        return None

    return {
        "gebied": gebied,
        "adres": adres,
        "postcode": postcode.replace(" ", "") if postcode else None,
        "aantal_personen": int(personen_ruw) if personen_ruw else None,
        "besluitdatum": besluit,
        "zaaknummer": zaaknummer,
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

    velden = parse_body(html)
    if velden is None:
        return

    stub.update(velden)
    stub["bruikbaar"] = True

    # Coördinaten voor de kaartlaag (best-effort). Postcode+adres via PDOK.
    try:
        geo = geocode_vrij(velden["adres"], "Rotterdam")
        stub["lat"], stub["lon"] = geo.lat, geo.lon
        if not stub.get("gebied") and geo.rotterdam_wijk:
            stub["gebied"] = geo.rotterdam_wijk
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

    if not index.meta.get("volledige_enumeratie_gedaan"):
        logger.info("Eenmalige volledige inventarisatie van het vergunningen-archief...")
        for pid, stub in enumereer_stubs().items():
            index.vergunningen.setdefault(pid, stub)
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
