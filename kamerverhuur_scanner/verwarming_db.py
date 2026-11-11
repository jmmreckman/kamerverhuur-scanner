"""SQLite-opslag voor de verwarmingsmodule (Tado-monitoring + terugschakeling).

Waarom een eigen SQLite-bestand (los van `communicatie.db`)? De verwarmingsdata
is een tijdreeks: per zone (= radiatorknop/thermostaat) elke ~15 minuten een
meting (binnentemperatuur, setpoint, stookvermogen). Daar wil je op kunnen
filteren/aggregeren ("laatste stand per kamer", "gemiddelde van deze week",
"hoe vaak boven 22°"). Dat is in SQL natuurlijker dan in losse JSON, en
`sqlite3` zit in Python zelf (geen extra dependency). Het bestand staat in
`state_dir` (= `/app/data` op de VPS), dus het overleeft een deploy.

De tabellen koppelen Tado-zones aan panden/kamers uit de bestaande bronnen
(properties.json + de Huurders-sheet). Dit bestand bevat alleen de pure
opslaglaag - geen Flask, geen netwerk - zodat het los testbaar is.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

BESTANDSNAAM = "verwarming.db"

# Standaardwaarden voor een terugschakel-regel (de "gewoonte"). Bewust ruim:
# plafond 25°, elke 15 min een graad eraf tot 20°, en na 3 uur hoog naar 18°.
STANDAARD_MAX = 25.0
STANDAARD_STAP = 1.0
STANDAARD_INTERVAL_MIN = 15
STANDAARD_VLOER = 20.0
STANDAARD_NA_UREN = 3
STANDAARD_NACHT = 18.0

# Sensorwaarden hierbuiten zijn vrijwel zeker onzin (sensor in de zon, defect,
# of de knop staat los) - niet op sturen. Zie verwarming_regels.sensor_ok().
SENSOR_MIN = 5.0
SENSOR_MAX = 30.0


def _nu() -> str:
    """Huidige tijd als ISO-8601 (UTC) - sorteerbaar en ondubbelzinnig."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pad(state_dir: str) -> str:
    return os.path.join(state_dir, BESTANDSNAAM)


def verbind(db_pad: str) -> sqlite3.Connection:
    """Opent (en initialiseert) de database. Row-factory = sqlite3.Row zodat
    rijen op kolomnaam benaderbaar zijn."""
    conn = sqlite3.connect(db_pad)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


# --- schema -----------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS zone_config (
    provider TEXT NOT NULL DEFAULT 'tado',
    home_id TEXT NOT NULL,
    home_naam TEXT,
    zone_id INTEGER NOT NULL,
    zone_naam TEXT,
    device_serial TEXT,
    laatst_gezien TEXT,
    -- door de gebruiker ingesteld (koppelscherm):
    pand_slug TEXT,
    kamer TEXT,
    -- terugschakel-regel (standaard uit):
    regel_actief INTEGER NOT NULL DEFAULT 0,
    max_temp REAL,
    stap REAL,
    interval_min INTEGER,
    vloer_temp REAL,
    na_uren INTEGER,
    nacht_temp REAL,
    -- inactiviteit-setback-probe (Fase 1, standaard uit):
    setback_actief INTEGER NOT NULL DEFAULT 0,
    setback_na_dagen REAL,
    setback_drempel REAL,
    setback_temp REAL,
    PRIMARY KEY (provider, home_id, zone_id)
);

CREATE TABLE IF NOT EXISTS sample (
    provider TEXT NOT NULL DEFAULT 'tado',
    home_id TEXT NOT NULL,
    zone_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    inside REAL,
    humidity REAL,
    setpoint REAL,
    power TEXT,
    heating_pct REAL,
    overlay_type TEXT,
    online INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sample_zone_ts
    ON sample (provider, home_id, zone_id, ts);

-- Status van een lopende terugschakeling per zone (de engine houdt zelf bij
-- sinds wanneer hij aan het afbouwen is en wat hij als laatste heeft gezet,
-- omdat het verlagen van het setpoint de "staat al hoog"-detectie zou wissen).
CREATE TABLE IF NOT EXISTS terugschakeling (
    provider TEXT NOT NULL DEFAULT 'tado',
    home_id TEXT NOT NULL,
    zone_id INTEGER NOT NULL,
    actief_sinds TEXT,
    laatste_doel REAL,
    PRIMARY KEY (provider, home_id, zone_id)
);

-- Aanwezigheid per zone (Fase 1: afgeleid uit thermostaat-interactie).
CREATE TABLE IF NOT EXISTS aanwezigheid (
    provider TEXT NOT NULL DEFAULT 'tado',
    home_id TEXT NOT NULL,
    zone_id INTEGER NOT NULL,
    laatste_interactie TEXT,
    setback_sinds TEXT,
    setback_doel REAL,
    PRIMARY KEY (provider, home_id, zone_id)
);
"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    # Migratie: 'online' is later toegevoegd - voeg de kolom toe aan een
    # bestaande sample-tabel (CREATE IF NOT EXISTS raakt een bestaande tabel niet).
    kolommen = [r[1] for r in conn.execute("PRAGMA table_info(sample)").fetchall()]
    if "online" not in kolommen:
        conn.execute("ALTER TABLE sample ADD COLUMN online INTEGER")
    # Migratie: 'humidity' (luchtvochtigheid %) later toegevoegd.
    if "humidity" not in kolommen:
        conn.execute("ALTER TABLE sample ADD COLUMN humidity REAL")
    # Migratie: setback-kolommen later toegevoegd aan een bestaande zone_config.
    zc_kol = [r[1] for r in conn.execute("PRAGMA table_info(zone_config)").fetchall()]
    for kol, definitie in (("setback_actief", "INTEGER NOT NULL DEFAULT 0"),
                           ("setback_na_dagen", "REAL"),
                           ("setback_drempel", "REAL"),
                           ("setback_temp", "REAL")):
        if kol not in zc_kol:
            conn.execute(f"ALTER TABLE zone_config ADD COLUMN {kol} {definitie}")
    conn.commit()


# --- zones: ontdekken (poll) + koppelen/regelen (UI) ------------------------

def registreer_zone(conn, provider, home_id, home_naam, zone_id, zone_naam,
                    device_serial=None) -> None:
    """Zorgt dat een (door de poll ontdekte) zone in zone_config staat en werkt
    de ontdekte velden bij. Raakt de door de gebruiker ingestelde koppeling/regel
    NIET aan (INSERT OR IGNORE + gerichte UPDATE)."""
    conn.execute(
        "INSERT OR IGNORE INTO zone_config (provider, home_id, zone_id) VALUES (?,?,?)",
        (provider, str(home_id), int(zone_id)),
    )
    conn.execute(
        "UPDATE zone_config SET home_naam=?, zone_naam=?, device_serial=COALESCE(?, device_serial),"
        " laatst_gezien=? WHERE provider=? AND home_id=? AND zone_id=?",
        (home_naam, zone_naam, device_serial, _nu(), provider, str(home_id), int(zone_id)),
    )
    conn.commit()


def zet_koppeling(conn, provider, home_id, zone_id, pand_slug, kamer) -> None:
    """Koppelt een zone aan een pand + kamer (of ontkoppelt met lege waarden)."""
    conn.execute(
        "UPDATE zone_config SET pand_slug=?, kamer=? WHERE provider=? AND home_id=? AND zone_id=?",
        (pand_slug or None, kamer or None, provider, str(home_id), int(zone_id)),
    )
    conn.commit()


def zet_regel(conn, provider, home_id, zone_id, *, regel_actief, max_temp, stap,
              interval_min, vloer_temp, na_uren, nacht_temp) -> None:
    """Zet de terugschakel-regel voor een zone."""
    conn.execute(
        "UPDATE zone_config SET regel_actief=?, max_temp=?, stap=?, interval_min=?,"
        " vloer_temp=?, na_uren=?, nacht_temp=? WHERE provider=? AND home_id=? AND zone_id=?",
        (1 if regel_actief else 0, max_temp, stap, interval_min, vloer_temp,
         na_uren, nacht_temp, provider, str(home_id), int(zone_id)),
    )
    conn.commit()


def zone(conn, provider, home_id, zone_id):
    return conn.execute(
        "SELECT * FROM zone_config WHERE provider=? AND home_id=? AND zone_id=?",
        (provider, str(home_id), int(zone_id)),
    ).fetchone()


def lijst_zones(conn, pand_slug=None, inclusief_ongekoppeld=False):
    """Zones, gesorteerd op home + naam. pand_slug gezet -> alleen die van dat
    pand (plus de nog niet-gekoppelde als inclusief_ongekoppeld)."""
    if pand_slug is None:
        return conn.execute(
            "SELECT * FROM zone_config ORDER BY home_naam, zone_naam"
        ).fetchall()
    if inclusief_ongekoppeld:
        return conn.execute(
            "SELECT * FROM zone_config WHERE pand_slug=? OR pand_slug IS NULL"
            " ORDER BY (pand_slug IS NULL), home_naam, zone_naam",
            (pand_slug,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM zone_config WHERE pand_slug=? ORDER BY home_naam, zone_naam",
        (pand_slug,),
    ).fetchall()


# --- metingen ---------------------------------------------------------------

def bewaar_sample(conn, provider, home_id, zone_id, *, inside, setpoint, power,
                  heating_pct, overlay_type, online=None, humidity=None, ts=None) -> None:
    # online: True->1, False->0, None->NULL (onbekend). humidity: % of None.
    online_val = None if online is None else (1 if online else 0)
    conn.execute(
        "INSERT INTO sample (provider, home_id, zone_id, ts, inside, humidity, setpoint, power,"
        " heating_pct, overlay_type, online) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (provider, str(home_id), int(zone_id), ts or _nu(), inside, humidity, setpoint, power,
         heating_pct, overlay_type, online_val),
    )
    conn.commit()


def laatste_sample(conn, provider, home_id, zone_id):
    return conn.execute(
        "SELECT * FROM sample WHERE provider=? AND home_id=? AND zone_id=?"
        " ORDER BY ts DESC LIMIT 1",
        (provider, str(home_id), int(zone_id)),
    ).fetchone()


def historie(conn, provider, home_id, zone_id, sinds=None, limiet=500):
    if sinds:
        rows = conn.execute(
            "SELECT * FROM sample WHERE provider=? AND home_id=? AND zone_id=? AND ts>=?"
            " ORDER BY ts DESC LIMIT ?",
            (provider, str(home_id), int(zone_id), sinds, limiet),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sample WHERE provider=? AND home_id=? AND zone_id=?"
            " ORDER BY ts DESC LIMIT ?",
            (provider, str(home_id), int(zone_id), limiet),
        ).fetchall()
    return list(reversed(rows))  # oplopend in tijd voor een grafiek


def conclusies(conn, provider, home_id, zone_id, sinds=None, drempel=22.0):
    """Samenvattende cijfers over een periode: gemiddelde binnentemp/setpoint,
    hoogste setpoint, aandeel metingen met setpoint >= drempel, aantal metingen."""
    # Offline (bevroren) metingen tellen niet mee in de conclusies.
    waar = "provider=? AND home_id=? AND zone_id=? AND (online IS NULL OR online=1)"
    args = [provider, str(home_id), int(zone_id)]
    if sinds:
        waar += " AND ts>=?"; args.append(sinds)
    row = conn.execute(
        f"SELECT COUNT(*) n, AVG(inside) gem_binnen, AVG(setpoint) gem_setpoint,"
        f" MAX(setpoint) max_setpoint, MIN(ts) van, MAX(ts) tot,"
        f" AVG(humidity) gem_vocht, MAX(humidity) max_vocht,"
        f" SUM(CASE WHEN setpoint>=? THEN 1 ELSE 0 END) boven"
        f" FROM sample WHERE {waar}",
        [drempel] + args,
    ).fetchone()
    n = row["n"] or 0
    return {
        "aantal": n,
        "gem_binnen": round(row["gem_binnen"], 1) if row["gem_binnen"] is not None else None,
        "gem_setpoint": round(row["gem_setpoint"], 1) if row["gem_setpoint"] is not None else None,
        "max_setpoint": row["max_setpoint"],
        "gem_vocht": round(row["gem_vocht"]) if row["gem_vocht"] is not None else None,
        "max_vocht": round(row["max_vocht"]) if row["max_vocht"] is not None else None,
        "drempel": drempel,
        "aandeel_boven": round(100.0 * row["boven"] / n) if n else 0,
        "van": row["van"],
        "tot": row["tot"],
    }


def lang_warme_zones(conn, pand_slug, sinds_iso, span_iso, drempel=22.0, min_n=1):
    """Zones van een pand die over het venster (sinds_iso .. nu) gemiddeld >= drempel
    zijn gemeten, die nog GEEN terugschakel-regel hebben, en waarvan de data ook echt
    ver genoeg terugreikt (MIN(ts) <= span_iso). Voor het 'Wat vraagt aandacht'-signaal:
    'deze kamer stookt al dagen hoog - overweeg een terugschakel-regel'."""
    return conn.execute(
        "SELECT zc.provider p, zc.home_id h, zc.zone_id z, zc.kamer kamer, zc.zone_naam zn,"
        " AVG(s.inside) gem, COUNT(*) n, MIN(s.ts) van"
        " FROM zone_config zc JOIN sample s"
        "  ON s.provider=zc.provider AND s.home_id=zc.home_id AND s.zone_id=zc.zone_id"
        " WHERE zc.pand_slug=? AND zc.regel_actief=0 AND s.ts>=?"
        "  AND (s.online IS NULL OR s.online=1) AND s.inside IS NOT NULL"
        " GROUP BY zc.provider, zc.home_id, zc.zone_id"
        " HAVING AVG(s.inside) >= ? AND COUNT(*) >= ? AND MIN(s.ts) <= ?",
        (pand_slug, sinds_iso, drempel, min_n, span_iso),
    ).fetchall()


def vochtige_zones(conn, pand_slug, sinds_iso, span_iso, drempel=70.0, min_n=1):
    """Zones van een pand die over het venster (sinds_iso .. nu) gemiddeld >= drempel%
    relatieve luchtvochtigheid zijn gemeten, en waarvan de data ook echt ver genoeg
    terugreikt (MIN(ts) <= span_iso). Voor het schimmel-signaal op 'Wat vraagt aandacht':
    'deze kamer is al dagen aanhoudend vochtig - schimmelrisico'. Alleen zones die vocht
    meten tellen mee (humidity IS NOT NULL -> in de praktijk Tado); staat LOS van een
    terugschakel-regel (schimmel heeft niets met de stooklimiet te maken)."""
    return conn.execute(
        "SELECT zc.provider p, zc.home_id h, zc.zone_id z, zc.kamer kamer, zc.zone_naam zn,"
        " AVG(s.humidity) gem, MAX(s.humidity) piek, COUNT(*) n, MIN(s.ts) van"
        " FROM zone_config zc JOIN sample s"
        "  ON s.provider=zc.provider AND s.home_id=zc.home_id AND s.zone_id=zc.zone_id"
        " WHERE zc.pand_slug=? AND s.ts>=?"
        "  AND (s.online IS NULL OR s.online=1) AND s.humidity IS NOT NULL"
        " GROUP BY zc.provider, zc.home_id, zc.zone_id"
        " HAVING AVG(s.humidity) >= ? AND COUNT(*) >= ? AND MIN(s.ts) <= ?",
        (pand_slug, sinds_iso, drempel, min_n, span_iso),
    ).fetchall()


def prune_samples(conn, ouder_dan_dagen=120) -> int:
    """Verwijdert ruwe metingen ouder dan N dagen (retentie). Geeft het aantal
    verwijderde rijen terug."""
    grens = (datetime.now(timezone.utc).timestamp() - ouder_dan_dagen * 86400)
    grens_iso = datetime.fromtimestamp(grens, tz=timezone.utc).isoformat(timespec="seconds")
    cur = conn.execute("DELETE FROM sample WHERE ts < ?", (grens_iso,))
    conn.commit()
    return cur.rowcount


# --- terugschakel-status (engine-state) -------------------------------------

def lees_terugschakeling(conn, provider, home_id, zone_id):
    return conn.execute(
        "SELECT * FROM terugschakeling WHERE provider=? AND home_id=? AND zone_id=?",
        (provider, str(home_id), int(zone_id)),
    ).fetchone()


def schrijf_terugschakeling(conn, provider, home_id, zone_id, actief_sinds, laatste_doel) -> None:
    conn.execute(
        "INSERT INTO terugschakeling (provider, home_id, zone_id, actief_sinds, laatste_doel)"
        " VALUES (?,?,?,?,?)"
        " ON CONFLICT(provider, home_id, zone_id) DO UPDATE SET actief_sinds=excluded.actief_sinds,"
        " laatste_doel=excluded.laatste_doel",
        (provider, str(home_id), int(zone_id), actief_sinds, laatste_doel),
    )
    conn.commit()


def wis_terugschakeling(conn, provider, home_id, zone_id) -> None:
    conn.execute(
        "DELETE FROM terugschakeling WHERE provider=? AND home_id=? AND zone_id=?",
        (provider, str(home_id), int(zone_id)),
    )
    conn.commit()


# --- aanwezigheid + setback-regel -------------------------------------------

def zet_setback_regel(conn, provider, home_id, zone_id, *, setback_actief,
                      na_dagen, drempel, setback_temp) -> None:
    conn.execute(
        "UPDATE zone_config SET setback_actief=?, setback_na_dagen=?, setback_drempel=?,"
        " setback_temp=? WHERE provider=? AND home_id=? AND zone_id=?",
        (1 if setback_actief else 0, na_dagen, drempel, setback_temp,
         provider, str(home_id), int(zone_id)),
    )
    conn.commit()


def lees_aanwezigheid(conn, provider, home_id, zone_id):
    return conn.execute(
        "SELECT * FROM aanwezigheid WHERE provider=? AND home_id=? AND zone_id=?",
        (provider, str(home_id), int(zone_id)),
    ).fetchone()


def schrijf_aanwezigheid(conn, provider, home_id, zone_id, laatste_interactie,
                         setback_sinds, setback_doel) -> None:
    conn.execute(
        "INSERT INTO aanwezigheid (provider, home_id, zone_id, laatste_interactie,"
        " setback_sinds, setback_doel) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(provider, home_id, zone_id) DO UPDATE SET"
        " laatste_interactie=excluded.laatste_interactie, setback_sinds=excluded.setback_sinds,"
        " setback_doel=excluded.setback_doel",
        (provider, str(home_id), int(zone_id), laatste_interactie, setback_sinds, setback_doel),
    )
    conn.commit()
