"""
Database schema en functies voor het Mentor AI Assistent systeem.
SQLite database met alle leerlingen, contacten, communicatie en documenten.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "mentor.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    """Maak alle tabellen aan als ze nog niet bestaan."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = get_connection()
    c = conn.cursor()

    # ── Leerlingen ──────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS leerlingen (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        magister_id     TEXT UNIQUE,
        voornaam        TEXT NOT NULL,
        tussenvoegsel   TEXT,
        achternaam      TEXT NOT NULL,
        geboortedatum   TEXT,
        klas            TEXT,
        leerjaar        INTEGER,
        notities        TEXT,                   -- vrije tekst, context voor AI
        aangemaakt_op   TEXT DEFAULT (datetime('now')),
        bijgewerkt_op   TEXT DEFAULT (datetime('now'))
    )""")

    # ── Contacten rondom een leerling ────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS contacten (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        leerling_id     INTEGER REFERENCES leerlingen(id) ON DELETE CASCADE,
        rol             TEXT NOT NULL,           -- ouder1, ouder2, voogd, jeugdarts, leerplichtambtenaar, therapeut, ...
        voornaam        TEXT,
        achternaam      TEXT,
        email           TEXT,
        telefoon        TEXT,
        organisatie     TEXT,                    -- bijv. GGD, gemeente
        notities        TEXT,
        aangemaakt_op   TEXT DEFAULT (datetime('now'))
    )""")

    # ── Communicatie (mails, Teams berichten, etc.) ──────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS communicatie (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        leerling_id     INTEGER REFERENCES leerlingen(id) ON DELETE SET NULL,
        bron            TEXT NOT NULL,           -- outlook, teams, magister, handmatig
        extern_id       TEXT,                    -- message-id uit Outlook / Teams
        richting        TEXT NOT NULL,           -- inkomend / uitgaand
        van_email       TEXT,
        aan_email       TEXT,
        onderwerp       TEXT,
        inhoud          TEXT,
        samenvatting    TEXT,                    -- AI-gegenereerde samenvatting
        datum           TEXT NOT NULL,
        verwerkt        INTEGER DEFAULT 0,       -- 0=nieuw, 1=verwerkt door AI
        actie_vereist   INTEGER DEFAULT 0,       -- AI: vereist dit een reactie?
        concept_reactie TEXT,                    -- AI-gegenereerde conceptmail
        aangemaakt_op   TEXT DEFAULT (datetime('now'))
    )""")

    # ── Documenten (PDF's uit Magister en andere bronnen) ────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS documenten (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        leerling_id     INTEGER REFERENCES leerlingen(id) ON DELETE CASCADE,
        bestandsnaam    TEXT NOT NULL,
        lokaal_pad      TEXT,                    -- pad naar gedownloade PDF
        bron            TEXT DEFAULT 'magister',
        categorie       TEXT,                    -- rapport, handelingsplan, verwijzing, ...
        datum_document  TEXT,
        samenvatting    TEXT,                    -- AI-gegenereerde samenvatting van PDF
        volledige_tekst TEXT,                    -- geëxtraheerde tekst uit PDF
        aangemaakt_op   TEXT DEFAULT (datetime('now'))
    )""")

    # ── Tijdlijn / stappen per leerling (chronologisch volgsysteem) ──────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS tijdlijn (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        leerling_id     INTEGER NOT NULL REFERENCES leerlingen(id) ON DELETE CASCADE,
        datum           TEXT NOT NULL,
        type            TEXT NOT NULL,           -- gesprek, mail, vergadering, verwijzing, besluit, document, notitie
        titel           TEXT NOT NULL,
        beschrijving    TEXT,
        gerelateerd_communicatie_id INTEGER REFERENCES communicatie(id),
        gerelateerd_document_id     INTEGER REFERENCES documenten(id),
        aangemaakt_door TEXT DEFAULT 'systeem',  -- systeem / mentor
        aangemaakt_op   TEXT DEFAULT (datetime('now'))
    )""")

    # ── Taken (voor de docent en/of voor het systeem) ────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS taken (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        leerling_id     INTEGER REFERENCES leerlingen(id) ON DELETE SET NULL,
        titel           TEXT NOT NULL,
        beschrijving    TEXT,
        prioriteit      TEXT DEFAULT 'normaal',  -- laag / normaal / hoog / urgent
        type            TEXT DEFAULT 'docent',   -- docent / systeem / beiden
        status          TEXT DEFAULT 'open',     -- open / bezig / klaar / vervallen
        deadline        TEXT,
        bron_communicatie_id INTEGER REFERENCES communicatie(id),
        aangemaakt_op   TEXT DEFAULT (datetime('now')),
        bijgewerkt_op   TEXT DEFAULT (datetime('now'))
    )""")

    # ── Sync log (bijhouden wanneer welke bron voor het laast gesynchroniseerd is) ──
    c.execute("""
    CREATE TABLE IF NOT EXISTS sync_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        bron            TEXT NOT NULL UNIQUE,    -- outlook, teams, magister, google_calendar
        laatste_sync    TEXT,
        laatste_item_id TEXT,                    -- voor incremental sync (bijv. Outlook deltaLink)
        status          TEXT DEFAULT 'nooit',    -- nooit / ok / fout
        foutmelding     TEXT,
        bijgewerkt_op   TEXT DEFAULT (datetime('now'))
    )""")

    # ── Dagelijkse briefings ─────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS briefings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        datum           TEXT NOT NULL UNIQUE,
        inhoud_html     TEXT,                    -- volledig HTML rapport
        inhoud_tekst    TEXT,                    -- platte tekst versie
        aangemaakt_op   TEXT DEFAULT (datetime('now'))
    )""")

    # ── Initialiseer sync log rijen ──────────────────────────────────────────
    for bron in ("outlook", "teams", "magister", "google_calendar"):
        c.execute("""
            INSERT OR IGNORE INTO sync_log (bron) VALUES (?)
        """, (bron,))

    conn.commit()
    conn.close()
    print(f"Database geïnitialiseerd: {DB_PATH}")


# ── Hulpfuncties ─────────────────────────────────────────────────────────────

def get_leerling(leerling_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM leerlingen WHERE id = ?", (leerling_id,)
    ).fetchone()
    conn.close()
    return row


def get_alle_leerlingen() -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM leerlingen ORDER BY achternaam, voornaam"
    ).fetchall()
    conn.close()
    return rows


def get_contacten(leerling_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM contacten WHERE leerling_id = ? ORDER BY rol", (leerling_id,)
    ).fetchall()
    conn.close()
    return rows


def get_tijdlijn(leerling_id: int, limit: int = 50) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM tijdlijn
        WHERE leerling_id = ?
        ORDER BY datum DESC
        LIMIT ?
    """, (leerling_id, limit)).fetchall()
    conn.close()
    return rows


def get_onverwerkte_communicatie() -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT c.*, l.voornaam, l.achternaam
        FROM communicatie c
        LEFT JOIN leerlingen l ON c.leerling_id = l.id
        WHERE c.verwerkt = 0
        ORDER BY c.datum DESC
    """).fetchall()
    conn.close()
    return rows


def sla_communicatie_op(data: dict) -> int:
    """Sla een bericht op. Geeft het nieuwe id terug."""
    conn = get_connection()
    c = conn.cursor()
    # Voorkom duplicaten op basis van extern_id
    if data.get("extern_id"):
        existing = c.execute(
            "SELECT id FROM communicatie WHERE extern_id = ? AND bron = ?",
            (data["extern_id"], data["bron"])
        ).fetchone()
        if existing:
            conn.close()
            return existing["id"]

    c.execute("""
        INSERT INTO communicatie
            (leerling_id, bron, extern_id, richting, van_email, aan_email,
             onderwerp, inhoud, datum)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("leerling_id"),
        data["bron"],
        data.get("extern_id"),
        data.get("richting", "inkomend"),
        data.get("van_email"),
        data.get("aan_email"),
        data.get("onderwerp"),
        data.get("inhoud"),
        data.get("datum", datetime.now().isoformat()),
    ))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def update_sync_log(bron: str, laatste_item_id: str = None, status: str = "ok", foutmelding: str = None):
    conn = get_connection()
    conn.execute("""
        UPDATE sync_log
        SET laatste_sync = datetime('now'),
            laatste_item_id = COALESCE(?, laatste_item_id),
            status = ?,
            foutmelding = ?,
            bijgewerkt_op = datetime('now')
        WHERE bron = ?
    """, (laatste_item_id, status, foutmelding, bron))
    conn.commit()
    conn.close()


def get_sync_status(bron: str) -> sqlite3.Row | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM sync_log WHERE bron = ?", (bron,)).fetchone()
    conn.close()
    return row


def voeg_tijdlijn_toe(leerling_id: int, datum: str, type_: str, titel: str,
                      beschrijving: str = None, communicatie_id: int = None,
                      document_id: int = None, aangemaakt_door: str = "systeem"):
    conn = get_connection()
    conn.execute("""
        INSERT INTO tijdlijn
            (leerling_id, datum, type, titel, beschrijving,
             gerelateerd_communicatie_id, gerelateerd_document_id, aangemaakt_door)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (leerling_id, datum, type_, titel, beschrijving,
          communicatie_id, document_id, aangemaakt_door))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_database()
