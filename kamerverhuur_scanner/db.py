"""SQLite-hoofddatabase voor Steenhub - de eigen database op de VPS waarin alle
pand- en huurdersgegevens staan, helemaal los van Google Sheets.

Eén bestand `steenhub.db` in `state_dir` (het blijvende data-volume, zie
Config.state_dir), met alle panden en - per pand - de kamers/huurders, de
betaalhistorie, de aanmeldingen, de bezichtigingen en de vertrokken huurders.
Google wordt alleen nog gebruikt voor Drive (documenten/backup), niet meer voor
de gegevens zelf.

Dit bestand bevat de verbinding, het schema (met kleine, idempotente migraties)
en de panden-opslag (lezen/schrijven/verwijderen). De per-pand kamers/historie/
aanmeldingen/bezichtigingen/vertrokken lopen via kamerverhuur_scanner/db_client.py
(DbClient), een drop-in vervanger van de oude SheetClient met exact dezelfde
methodes en retourtypes.

Concurrency: meerdere gunicorn-workers én de achtergrondscripts (dagelijkse
controle, winst-snapshot, mail-inname, verwarming-check) openen hetzelfde
bestand. WAL-modus + een ruime busy_timeout laten gelijktijdige lezers en één
schrijver netjes samenwerken; de schrijfacties zijn allemaal kort.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .config import Config
from .models import Pand
from .properties import find_pand, pand_uit_dict

# Lijst/dict-velden van een pand worden als JSON-tekst in één kolom bewaard; de
# rest als gewone kolommen, zodat de database ook met de hand te bewerken is
# (bv. `UPDATE panden SET hypotheek_rente_per_maand='850' WHERE slug='...'`).
_PANDEN_JSON_VELDEN = ("extra_bcc", "verhuurders", "sleutels")
# Alle (scalar) pand-kolommen naast slug en de JSON-velden, in formuliervolgorde.
_PANDEN_TEKST_VELDEN = (
    "naam", "google_sheet_id", "google_sheet_worksheet", "history_worksheet",
    "aanmeldingen_worksheet", "vertrokken_worksheet", "bunq_rekening_iban",
    "postcode", "plaats", "rekeninghouder_naam", "gedeelde_ruimtes",
    "bijzondere_bepalingen", "gemeente_meldpunt", "onderhoud_reserve_per_maand",
    "energiekosten_per_maand", "belasting_per_maand", "hypotheek_rente_per_maand",
    "hypotheek_last_per_maand", "hypotheek_schuld", "aantal_eigenaren", "kleur",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS panden (
    slug TEXT PRIMARY KEY,
    naam TEXT NOT NULL DEFAULT '',
    google_sheet_id TEXT NOT NULL DEFAULT '',
    google_sheet_worksheet TEXT NOT NULL DEFAULT 'Huurders',
    history_worksheet TEXT NOT NULL DEFAULT 'Historie',
    aanmeldingen_worksheet TEXT NOT NULL DEFAULT 'Aanmeldingen',
    vertrokken_worksheet TEXT NOT NULL DEFAULT 'Vertrokken',
    bunq_rekening_iban TEXT NOT NULL DEFAULT '',
    extra_bcc TEXT NOT NULL DEFAULT '[]',
    postcode TEXT NOT NULL DEFAULT '',
    plaats TEXT NOT NULL DEFAULT '',
    verhuurders TEXT NOT NULL DEFAULT '[]',
    rekeninghouder_naam TEXT NOT NULL DEFAULT '',
    gedeelde_ruimtes TEXT NOT NULL DEFAULT '',
    bijzondere_bepalingen TEXT NOT NULL DEFAULT '',
    gemeente_meldpunt TEXT NOT NULL DEFAULT '',
    heeft_bold_slot INTEGER NOT NULL DEFAULT 1,
    onderhoud_reserve_per_maand TEXT,
    energiekosten_per_maand TEXT,
    belasting_per_maand TEXT,
    hypotheek_rente_per_maand TEXT,
    hypotheek_last_per_maand TEXT,
    hypotheek_schuld TEXT,
    aantal_eigenaren TEXT,
    sleutels TEXT NOT NULL DEFAULT '[]',
    kleur TEXT NOT NULL DEFAULT '',
    volgorde INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS huurders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pand_slug TEXT NOT NULL,
    volgorde INTEGER NOT NULL DEFAULT 0,
    kamer TEXT NOT NULL DEFAULT '',
    naam TEXT NOT NULL DEFAULT '',
    verwacht_bedrag TEXT NOT NULL DEFAULT '0.00',
    iban TEXT,
    zoekwoord TEXT,
    kale_huurprijs TEXT,
    servicekosten TEXT,
    contract_einddatum TEXT,
    opmerking TEXT,
    beschikbaar INTEGER NOT NULL DEFAULT 0,
    advertentie_omschrijving TEXT,
    advertentie_map_id TEXT,
    email TEXT,
    telefoonnummer TEXT,
    geboortedatum TEXT,
    geboorteplaats TEXT,
    studentnummer TEXT,
    studierichting TEXT,
    borgsteller_naam TEXT,
    borgsteller_relatie TEXT,
    contract_startdatum TEXT,
    borg_bedrag TEXT,
    advertentie_prijs TEXT,
    advertentie_oppervlakte TEXT,
    advertentie_beschikbaar_per TEXT,
    advertentie_beschikbaar_tot TEXT,
    advertentie_borg TEXT,
    aanbod_verhuurd INTEGER NOT NULL DEFAULT 0,
    studenten_verplicht INTEGER NOT NULL DEFAULT 1,
    status TEXT,
    ontvangen_bedrag TEXT,
    laatst_gecontroleerd TEXT
);
CREATE INDEX IF NOT EXISTS idx_huurders_pand ON huurders(pand_slug, volgorde, id);

CREATE TABLE IF NOT EXISTS historie (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pand_slug TEXT NOT NULL,
    maand TEXT NOT NULL,
    kamer TEXT NOT NULL,
    huurder TEXT NOT NULL DEFAULT '',
    verwacht_bedrag TEXT NOT NULL DEFAULT '0.00',
    ontvangen_bedrag TEXT NOT NULL DEFAULT '0.00',
    status TEXT NOT NULL DEFAULT '',
    betaaldatum TEXT,
    UNIQUE(pand_slug, kamer, maand)
);
CREATE INDEX IF NOT EXISTS idx_historie_pand_kamer ON historie(pand_slug, kamer);

CREATE TABLE IF NOT EXISTS aanmeldingen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pand_slug TEXT NOT NULL,
    datum TEXT NOT NULL DEFAULT '',
    kamer TEXT NOT NULL DEFAULT '',
    naam TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    telefoon TEXT NOT NULL DEFAULT '',
    huidig_adres TEXT NOT NULL DEFAULT '',
    studie TEXT NOT NULL DEFAULT '',
    studentnummer TEXT NOT NULL DEFAULT '',
    gewenste_ingangsdatum TEXT NOT NULL DEFAULT '',
    gewenste_huurduur TEXT NOT NULL DEFAULT '',
    inkomstenbron TEXT NOT NULL DEFAULT '',
    inkomsten_bedrag TEXT NOT NULL DEFAULT '',
    borgsteller TEXT NOT NULL DEFAULT '',
    bezichtiging TEXT NOT NULL DEFAULT '',
    videobel_nummer TEXT NOT NULL DEFAULT '',
    bewijs_inschrijving TEXT NOT NULL DEFAULT '',
    borgsteller_naam TEXT NOT NULL DEFAULT '',
    borgsteller_relatie TEXT NOT NULL DEFAULT '',
    borgsteller_email TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_aanmeldingen_pand ON aanmeldingen(pand_slug, id);

CREATE TABLE IF NOT EXISTS bezichtigingen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pand_slug TEXT NOT NULL,
    datum TEXT NOT NULL DEFAULT '',
    tijd_start TEXT NOT NULL DEFAULT '',
    tijd_eind TEXT NOT NULL DEFAULT '',
    kamer TEXT NOT NULL DEFAULT '',
    naam TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    telefoon TEXT NOT NULL DEFAULT '',
    manier TEXT NOT NULL DEFAULT '',
    bel_nummer TEXT NOT NULL DEFAULT '',
    bevestigd_op TEXT NOT NULL DEFAULT '',
    token TEXT,
    reactie TEXT NOT NULL DEFAULT '',
    reactie_op TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_bezichtigingen_pand ON bezichtigingen(pand_slug, id);
CREATE INDEX IF NOT EXISTS idx_bezichtigingen_token ON bezichtigingen(token);

CREATE TABLE IF NOT EXISTS vertrokken (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pand_slug TEXT NOT NULL,
    kamer TEXT NOT NULL DEFAULT '',
    naam TEXT NOT NULL DEFAULT '',
    email TEXT,
    telefoonnummer TEXT,
    contract_einddatum TEXT,
    vertrokken_op TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vertrokken_pand ON vertrokken(pand_slug, id);
"""


def db_pad(config: Config) -> str:
    """Pad naar het SQLite-bestand - in state_dir (het blijvende data-volume)."""
    return os.path.join(config.state_dir, "steenhub.db")


def verbind(config: Config) -> sqlite3.Connection:
    """Opent (en initialiseert zo nodig) de hoofddatabase. Elke aanroep geeft een
    verse verbinding - net als de oude 'verse client per request'-aanpak, maar
    zonder netwerk/quota, dus goedkoop."""
    pad = db_pad(config)
    Path(pad).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(pad, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    _migreer_kolommen(conn)
    conn.commit()
    return conn


# Kolommen die na de eerste release zijn toegevoegd. CREATE TABLE IF NOT EXISTS
# raakt een al bestaande tabel niet aan, dus nieuwe kolommen voegen we los toe
# (idempotent: alleen als ze nog niet bestaan). Zo migreert de bestaande
# productie-database zichzelf bij de eerstvolgende start.
_EXTRA_KOLOMMEN = {
    "huurders": [("studenten_verplicht", "INTEGER NOT NULL DEFAULT 1")],
    "panden": [("hypotheek_schuld", "TEXT")],
    "bezichtigingen": [
        ("token", "TEXT"),
        ("reactie", "TEXT NOT NULL DEFAULT ''"),
        ("reactie_op", "TEXT NOT NULL DEFAULT ''"),
    ],
}


def _migreer_kolommen(conn: sqlite3.Connection) -> None:
    for tabel, kolommen in _EXTRA_KOLOMMEN.items():
        bestaand = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabel})")}
        if not bestaand:
            continue  # tabel bestaat (nog) niet -> niets te migreren
        for naam, definitie in kolommen:
            if naam not in bestaand:
                conn.execute(f"ALTER TABLE {tabel} ADD COLUMN {naam} {definitie}")


# --- Panden ---------------------------------------------------------------

def _pand_rij_naar_item(row: sqlite3.Row) -> dict:
    item = {"slug": row["slug"], "heeft_bold_slot": bool(row["heeft_bold_slot"])}
    for veld in _PANDEN_TEKST_VELDEN:
        item[veld] = row[veld]
    for veld in _PANDEN_JSON_VELDEN:
        ruw = row[veld]
        try:
            item[veld] = json.loads(ruw) if ruw else []
        except (json.JSONDecodeError, TypeError):
            item[veld] = []
    return item


def laad_panden(config: Config) -> list[Pand]:
    """Alle panden uit de database, in de opgeslagen volgorde.

    Transitie-vangnet: zolang de panden-tabel nog leeg is (bv. vlak na de
    uitrol, vóór `scripts.migreer_naar_db` is gedraaid), valt dit terug op het
    oude properties.json. Zo blijft de site gewoon panden tonen tussen de
    uitrol en de migratie in. Zodra er panden in de database staan (na migratie
    of na "Pand aanmaken"), is de database leidend en wordt het bestand
    genegeerd - properties.json mag daarna weg."""
    conn = verbind(config)
    try:
        rows = conn.execute("SELECT * FROM panden ORDER BY volgorde, rowid").fetchall()
    finally:
        conn.close()
    if rows:
        return [pand_uit_dict(_pand_rij_naar_item(r)) for r in rows]
    try:
        from .properties import load_properties
        return load_properties(config.properties_file)
    except Exception:  # noqa: BLE001 - geen/ongeldig bestand = gewoon (nog) geen panden
        return []


def laad_panden_ruw(config: Config) -> list[dict]:
    """Zoals laad_panden, maar geeft de ruwe opgeslagen dicts terug (slug,
    genormaliseerde velden, JSON-velden al gedecodeerd naar lijsten/dicts) in
    plaats van Pand-objecten - handig om precies te zien wat er is opgeslagen
    (gebruikt in de tests). Géén properties.json-vangnet."""
    conn = verbind(config)
    try:
        rows = conn.execute("SELECT * FROM panden ORDER BY volgorde, rowid").fetchall()
    finally:
        conn.close()
    return [_pand_rij_naar_item(r) for r in rows]


def zet_pand(config: Config, slug: str, gegevens: dict) -> None:
    """Voegt een pand toe of werkt 'm bij (op slug) - zelfde contract als de oude
    properties.zet_pand, maar naar de database. `gegevens` is de dict uit het
    pand-formulier (zie webapp/app.py:_pand_gegevens_uit_form)."""
    kolommen = {}
    for veld in _PANDEN_TEKST_VELDEN:
        waarde = gegevens.get(veld)
        kolommen[veld] = "" if waarde is None and veld not in _OPTIONELE_TEKST else waarde
    for veld in _PANDEN_JSON_VELDEN:
        kolommen[veld] = json.dumps(gegevens.get(veld) or [])
    kolommen["heeft_bold_slot"] = 1 if gegevens.get("heeft_bold_slot", True) else 0

    conn = verbind(config)
    try:
        bestaat = conn.execute("SELECT 1 FROM panden WHERE slug = ?", (slug,)).fetchone()
        if bestaat:
            sets = ", ".join(f"{k} = :{k}" for k in kolommen)
            conn.execute(f"UPDATE panden SET {sets} WHERE slug = :slug", {**kolommen, "slug": slug})
        else:
            volgende = conn.execute("SELECT COALESCE(MAX(volgorde), 0) + 1 AS v FROM panden").fetchone()["v"]
            velden = ["slug", *kolommen.keys(), "volgorde"]
            plaatshouders = ", ".join(f":{k}" for k in velden)
            conn.execute(
                f"INSERT INTO panden ({', '.join(velden)}) VALUES ({plaatshouders})",
                {"slug": slug, **kolommen, "volgorde": volgende},
            )
        conn.commit()
    finally:
        conn.close()


def verwijder_pand(config: Config, slug: str) -> None:
    """Verwijdert een pand én al zijn kamers/historie/aanmeldingen/bezichtigingen/
    vertrokken huurders uit de database."""
    conn = verbind(config)
    try:
        for tabel in ("huurders", "historie", "aanmeldingen", "bezichtigingen", "vertrokken"):
            conn.execute(f"DELETE FROM {tabel} WHERE pand_slug = ?", (slug,))
        conn.execute("DELETE FROM panden WHERE slug = ?", (slug,))
        conn.commit()
    finally:
        conn.close()


# Pand-bedragen/aantal_eigenaren mogen NULL blijven (leeg) i.p.v. "" - zodat
# pand_uit_dict ze als None (niet ingevuld) ziet.
_OPTIONELE_TEKST = frozenset({
    "onderhoud_reserve_per_maand", "energiekosten_per_maand", "belasting_per_maand",
    "hypotheek_rente_per_maand", "hypotheek_last_per_maand", "hypotheek_schuld",
    "aantal_eigenaren",
})

__all__ = ["db_pad", "verbind", "laad_panden", "zet_pand", "verwijder_pand", "find_pand"]
