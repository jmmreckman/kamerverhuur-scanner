"""SQLite-opslag voor de huurderscommunicatie- en onderhoudsmodule (Fase 1).

Waarom SQLite en niet (zoals de rest van de app) JSON-state of Google Sheets?
De module draait op threads met berichten, tickets met statussen en een
goedkeuringswachtrij - daar wil je op kunnen filteren/sorteren ("alle open
klussen over alle panden, nieuwste boven", "alle berichten van deze huurder").
Dat is in SQL veel natuurlijker dan in losse JSON-bestanden, en `sqlite3` zit
in Python zelf (geen extra dependency). Het bestand staat in `state_dir`
(= `/app/data` op de VPS), dus het overleeft een deploy/herbuild net als de
rest van de data.

Panden (`properties.json`) en huurders (Google Sheets) blijven de bron van
waarheid voor pand/huurder-stamdata; de `contacten`-tabel hier is een
afgeleide kopie (geseed vanuit de Huurders-sheet) plus de communicatie-extra's
(samenvatting, gekoppelde e-mailadressen). Dit bestand bevat alleen de pure
opslaglaag - geen Flask, geen netwerk - zodat het los testbaar is.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

BESTANDSNAAM = "communicatie.db"

# Statussen (als losse constanten zodat ze consistent blijven tussen code en UI).
KLUS_OPEN = "open"
KLUS_VAKMAN = "vakman-ingeschakeld"
KLUS_WACHT_HUURDER = "wacht-op-huurder"
KLUS_AFGEROND = "afgerond"
KLUS_OPEN_STATUSSEN = (KLUS_OPEN, KLUS_VAKMAN, KLUS_WACHT_HUURDER)

ACTIE_OPEN = "open"
ACTIE_GOEDGEKEURD = "goedgekeurd"
ACTIE_VERZONDEN = "verzonden"
ACTIE_VERWORPEN = "verworpen"


def _nu() -> str:
    """Huidige tijd als ISO-8601 (UTC) string - sorteerbaar en ondubbelzinnig."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pad(state_dir: str) -> str:
    return os.path.join(state_dir, BESTANDSNAAM)


def verbind(db_pad: str) -> sqlite3.Connection:
    """Opent (en initialiseert) de database. Row-factory = sqlite3.Row zodat
    rijen als dict-achtig (op kolomnaam) benaderbaar zijn; foreign keys aan."""
    conn = sqlite3.connect(db_pad)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


# --- schema -----------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacten (
    id INTEGER PRIMARY KEY,
    naam TEXT NOT NULL,
    pand_slug TEXT,
    kamer TEXT,
    telefoon TEXT,
    actief INTEGER NOT NULL DEFAULT 1,
    samenvatting TEXT,
    samenvatting_bijgewerkt TEXT,
    aangemaakt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contact_emails (
    contact_id INTEGER NOT NULL REFERENCES contacten(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    PRIMARY KEY (contact_id, email)
);
CREATE INDEX IF NOT EXISTS idx_contact_emails_email ON contact_emails(email);

CREATE TABLE IF NOT EXISTS vakmannen (
    id INTEGER PRIMARY KEY,
    naam TEXT NOT NULL,
    vak TEXT,
    email TEXT,
    telefoon TEXT,
    actief INTEGER NOT NULL DEFAULT 1,
    aangemaakt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS klussen (
    id INTEGER PRIMARY KEY,
    contact_id INTEGER REFERENCES contacten(id) ON DELETE SET NULL,
    pand_slug TEXT,
    kamer TEXT,
    titel TEXT NOT NULL,
    omschrijving TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    vakman_id INTEGER REFERENCES vakmannen(id) ON DELETE SET NULL,
    aangemaakt TEXT NOT NULL,
    laatste_update TEXT NOT NULL,
    afgerond_op TEXT
);
CREATE INDEX IF NOT EXISTS idx_klussen_status ON klussen(status, laatste_update);

CREATE TABLE IF NOT EXISTS berichten (
    id INTEGER PRIMARY KEY,
    contact_id INTEGER REFERENCES contacten(id) ON DELETE SET NULL,
    pand_slug TEXT,
    kanaal TEXT NOT NULL,
    richting TEXT NOT NULL,
    van TEXT,
    naar TEXT,
    cc TEXT,
    onderwerp TEXT,
    body TEXT,
    datum TEXT NOT NULL,
    bron TEXT,
    message_id TEXT,
    thread_id TEXT,
    klus_id INTEGER REFERENCES klussen(id) ON DELETE SET NULL,
    aangemaakt TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_berichten_message_id
    ON berichten(message_id) WHERE message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_berichten_contact ON berichten(contact_id, datum);
CREATE INDEX IF NOT EXISTS idx_berichten_klus ON berichten(klus_id, datum);

CREATE TABLE IF NOT EXISTS acties (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    contact_id INTEGER REFERENCES contacten(id) ON DELETE SET NULL,
    pand_slug TEXT,
    klus_id INTEGER REFERENCES klussen(id) ON DELETE CASCADE,
    ontvanger TEXT,
    concept_onderwerp TEXT,
    concept_body TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    aangemaakt TEXT NOT NULL,
    verzonden_op TEXT
);
CREATE INDEX IF NOT EXISTS idx_acties_status ON acties(status, aangemaakt);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Maakt alle tabellen/indices aan als ze nog niet bestaan (idempotent)."""
    conn.executescript(_SCHEMA)
    conn.commit()


# --- contacten --------------------------------------------------------------

def upsert_contact(
    conn: sqlite3.Connection,
    naam: str,
    pand_slug: str | None = None,
    kamer: str | None = None,
    telefoon: str | None = None,
    emails: list[str] | None = None,
    actief: bool = True,
) -> int:
    """Maakt een contact aan, of werkt een bestaand contact bij wanneer een van
    de opgegeven e-mailadressen al aan een contact hangt (match op e-mail). Geeft
    het contact-id terug. E-mailadressen worden genormaliseerd (trim + lowercase)
    en als set toegevoegd (bestaande blijven staan).

    Zonder e-mail (of zonder match) wordt altijd een nieuw contact aangemaakt -
    e-mail is immers de koppelsleutel; naam alleen is te onbetrouwbaar om op te
    de-dupliceren."""
    schone_emails = _normaliseer_emails(emails)

    bestaand_id = None
    for email in schone_emails:
        rij = conn.execute(
            "SELECT contact_id FROM contact_emails WHERE email = ?", (email,)
        ).fetchone()
        if rij is not None:
            bestaand_id = rij["contact_id"]
            break

    if bestaand_id is None:
        cur = conn.execute(
            "INSERT INTO contacten (naam, pand_slug, kamer, telefoon, actief, aangemaakt) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (naam, pand_slug, kamer, telefoon, 1 if actief else 0, _nu()),
        )
        contact_id = int(cur.lastrowid)
    else:
        contact_id = int(bestaand_id)
        # Alleen niet-lege nieuwe waarden overschrijven, zodat een seed-run geen
        # handmatig ingevulde gegevens leegmaakt.
        velden = {"naam": naam, "pand_slug": pand_slug, "kamer": kamer, "telefoon": telefoon}
        zetten = {k: v for k, v in velden.items() if v}
        if zetten:
            kolommen = ", ".join(f"{k} = ?" for k in zetten)
            conn.execute(
                f"UPDATE contacten SET {kolommen} WHERE id = ?",
                (*zetten.values(), contact_id),
            )

    for email in schone_emails:
        conn.execute(
            "INSERT OR IGNORE INTO contact_emails (contact_id, email) VALUES (?, ?)",
            (contact_id, email),
        )
    conn.commit()
    return contact_id


def seed_contact(
    conn: sqlite3.Connection,
    *,
    naam: str,
    pand_slug: str,
    kamer: str | None = None,
    email: str | None = None,
    telefoon: str | None = None,
) -> int:
    """Zorgt dat er precies één contact bestaat voor een huurder uit de
    Huurders-sheet, en werkt de stamgegevens bij. Matcht eerst op e-mailadres
    (de koppelsleutel); heeft de huurder geen e-mail in de sheet, dan op
    pand+naam, zodat herhaald seeden/openen geen dubbele contacten oplevert.
    Alleen niet-lege nieuwe waarden overschrijven bestaande (zodat handmatig
    aangevulde gegevens blijven staan)."""
    emails = _normaliseer_emails([email] if email else None)

    contact_id = None
    for e in emails:
        rij = conn.execute(
            "SELECT contact_id FROM contact_emails WHERE email = ?", (e,)
        ).fetchone()
        if rij is not None:
            contact_id = int(rij["contact_id"])
            break
    if contact_id is None and not emails:
        rij = conn.execute(
            "SELECT id FROM contacten WHERE pand_slug IS ? AND naam = ? ORDER BY id LIMIT 1",
            (pand_slug, naam),
        ).fetchone()
        if rij is not None:
            contact_id = int(rij["id"])

    if contact_id is None:
        cur = conn.execute(
            "INSERT INTO contacten (naam, pand_slug, kamer, telefoon, actief, aangemaakt) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (naam, pand_slug, kamer, telefoon, _nu()),
        )
        contact_id = int(cur.lastrowid)
    else:
        velden = {"naam": naam, "pand_slug": pand_slug, "kamer": kamer, "telefoon": telefoon}
        zetten = {k: v for k, v in velden.items() if v}
        if zetten:
            kolommen = ", ".join(f"{k} = ?" for k in zetten)
            conn.execute(
                f"UPDATE contacten SET {kolommen} WHERE id = ?", (*zetten.values(), contact_id)
            )

    for e in emails:
        conn.execute(
            "INSERT OR IGNORE INTO contact_emails (contact_id, email) VALUES (?, ?)",
            (contact_id, e),
        )
    conn.commit()
    return contact_id


def _normaliseer_emails(emails: list[str] | None) -> list[str]:
    schoon = []
    for e in emails or []:
        e = (e or "").strip().lower()
        if e and e not in schoon:
            schoon.append(e)
    return schoon


def get_contact(conn: sqlite3.Connection, contact_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM contacten WHERE id = ?", (contact_id,)).fetchone()


def get_contact_op_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    rij = conn.execute(
        "SELECT c.* FROM contacten c JOIN contact_emails e ON e.contact_id = c.id "
        "WHERE e.email = ?",
        (email,),
    ).fetchone()
    return rij


def emails_van_contact(conn: sqlite3.Connection, contact_id: int) -> list[str]:
    rijen = conn.execute(
        "SELECT email FROM contact_emails WHERE contact_id = ? ORDER BY email", (contact_id,)
    ).fetchall()
    return [r["email"] for r in rijen]


def lijst_contacten(
    conn: sqlite3.Connection, pand_slugs: list[str] | None = None, alleen_actief: bool = True
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM contacten"
    voorwaarden, params = [], []
    if alleen_actief:
        voorwaarden.append("actief = 1")
    if pand_slugs is not None:
        voorwaarden.append(f"pand_slug IN ({_plaatshouders(pand_slugs)})")
        params.extend(pand_slugs)
    if voorwaarden:
        sql += " WHERE " + " AND ".join(voorwaarden)
    sql += " ORDER BY naam COLLATE NOCASE"
    return conn.execute(sql, params).fetchall()


def zet_samenvatting(conn: sqlite3.Connection, contact_id: int, tekst: str) -> None:
    conn.execute(
        "UPDATE contacten SET samenvatting = ?, samenvatting_bijgewerkt = ? WHERE id = ?",
        (tekst, _nu(), contact_id),
    )
    conn.commit()


# --- berichten --------------------------------------------------------------

def voeg_bericht_toe(
    conn: sqlite3.Connection,
    *,
    contact_id: int | None,
    pand_slug: str | None,
    kanaal: str,
    richting: str,
    van: str | None = None,
    naar: str | None = None,
    cc: str | None = None,
    onderwerp: str | None = None,
    body: str | None = None,
    datum: str | None = None,
    bron: str | None = None,
    message_id: str | None = None,
    thread_id: str | None = None,
    klus_id: int | None = None,
) -> int | None:
    """Voegt een bericht toe. Als er al een bericht met hetzelfde (niet-lege)
    `message_id` bestaat, wordt niets toegevoegd en None teruggegeven (dedup) -
    handig bij de Gmail-backfill en de latere IMAP-inname die hetzelfde bericht
    opnieuw kunnen tegenkomen."""
    if message_id:
        bestaand = conn.execute(
            "SELECT id FROM berichten WHERE message_id = ?", (message_id,)
        ).fetchone()
        if bestaand is not None:
            return None
    cur = conn.execute(
        "INSERT INTO berichten (contact_id, pand_slug, kanaal, richting, van, naar, cc, "
        "onderwerp, body, datum, bron, message_id, thread_id, klus_id, aangemaakt) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (contact_id, pand_slug, kanaal, richting, van, naar, cc, onderwerp, body,
         datum or _nu(), bron, message_id, thread_id, klus_id, _nu()),
    )
    conn.commit()
    return int(cur.lastrowid)


def berichten_van_contact(conn: sqlite3.Connection, contact_id: int) -> list[sqlite3.Row]:
    """Alle berichten van een contact, chronologisch (oudste eerst) - voor de
    tijdlijn op de huurderspagina."""
    return conn.execute(
        "SELECT * FROM berichten WHERE contact_id = ? ORDER BY datum, id", (contact_id,)
    ).fetchall()


def berichten_van_klus(conn: sqlite3.Connection, klus_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM berichten WHERE klus_id = ? ORDER BY datum, id", (klus_id,)
    ).fetchall()


# --- klussen (onderhoudstickets) -------------------------------------------

def maak_klus(
    conn: sqlite3.Connection,
    *,
    titel: str,
    pand_slug: str | None = None,
    contact_id: int | None = None,
    kamer: str | None = None,
    omschrijving: str | None = None,
    status: str = KLUS_OPEN,
) -> int:
    nu = _nu()
    cur = conn.execute(
        "INSERT INTO klussen (contact_id, pand_slug, kamer, titel, omschrijving, status, "
        "aangemaakt, laatste_update) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (contact_id, pand_slug, kamer, titel, omschrijving, status, nu, nu),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_klus(conn: sqlite3.Connection, klus_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM klussen WHERE id = ?", (klus_id,)).fetchone()


def lijst_klussen(
    conn: sqlite3.Connection,
    pand_slugs: list[str] | None = None,
    status: str | None = None,
    alleen_open: bool = False,
) -> list[sqlite3.Row]:
    """Tickets, nieuwste wijziging bovenaan. `pand_slugs` beperkt tot panden
    waar de gebruiker bij mag (None = geen beperking). `alleen_open` filtert op
    de niet-afgeronde statussen."""
    sql = "SELECT * FROM klussen"
    voorwaarden, params = [], []
    if pand_slugs is not None:
        voorwaarden.append(f"pand_slug IN ({_plaatshouders(pand_slugs)})")
        params.extend(pand_slugs)
    if status is not None:
        voorwaarden.append("status = ?")
        params.append(status)
    elif alleen_open:
        voorwaarden.append(f"status IN ({_plaatshouders(KLUS_OPEN_STATUSSEN)})")
        params.extend(KLUS_OPEN_STATUSSEN)
    if voorwaarden:
        sql += " WHERE " + " AND ".join(voorwaarden)
    sql += " ORDER BY laatste_update DESC, id DESC"
    return conn.execute(sql, params).fetchall()


def zet_klus_status(conn: sqlite3.Connection, klus_id: int, status: str) -> None:
    nu = _nu()
    afgerond = nu if status == KLUS_AFGEROND else None
    conn.execute(
        "UPDATE klussen SET status = ?, laatste_update = ?, "
        "afgerond_op = CASE WHEN ? IS NOT NULL THEN ? ELSE afgerond_op END WHERE id = ?",
        (status, nu, afgerond, afgerond, klus_id),
    )
    conn.commit()


def koppel_vakman(conn: sqlite3.Connection, klus_id: int, vakman_id: int | None) -> None:
    conn.execute(
        "UPDATE klussen SET vakman_id = ?, laatste_update = ? WHERE id = ?",
        (vakman_id, _nu(), klus_id),
    )
    conn.commit()


def raak_klus_aan(conn: sqlite3.Connection, klus_id: int) -> None:
    """Zet laatste_update op nu (bv. na een nieuw bericht), zodat het ticket
    bovenaan de lijst komt."""
    conn.execute("UPDATE klussen SET laatste_update = ? WHERE id = ?", (_nu(), klus_id))
    conn.commit()


# --- vakmannen --------------------------------------------------------------

def voeg_vakman_toe(
    conn: sqlite3.Connection, naam: str, vak: str | None = None,
    email: str | None = None, telefoon: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO vakmannen (naam, vak, email, telefoon, aangemaakt) VALUES (?, ?, ?, ?, ?)",
        (naam, vak, email, telefoon, _nu()),
    )
    conn.commit()
    return int(cur.lastrowid)


def lijst_vakmannen(conn: sqlite3.Connection, alleen_actief: bool = True) -> list[sqlite3.Row]:
    sql = "SELECT * FROM vakmannen"
    if alleen_actief:
        sql += " WHERE actief = 1"
    sql += " ORDER BY naam COLLATE NOCASE"
    return conn.execute(sql).fetchall()


def get_vakman(conn: sqlite3.Connection, vakman_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM vakmannen WHERE id = ?", (vakman_id,)).fetchone()


def zet_vakman_actief(conn: sqlite3.Connection, vakman_id: int, actief: bool) -> None:
    conn.execute(
        "UPDATE vakmannen SET actief = ? WHERE id = ?", (1 if actief else 0, vakman_id)
    )
    conn.commit()


# --- acties (goedkeuringswachtrij) -----------------------------------------

def maak_actie(
    conn: sqlite3.Connection,
    *,
    type: str,
    concept_body: str,
    concept_onderwerp: str | None = None,
    contact_id: int | None = None,
    pand_slug: str | None = None,
    klus_id: int | None = None,
    ontvanger: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO acties (type, contact_id, pand_slug, klus_id, ontvanger, "
        "concept_onderwerp, concept_body, status, aangemaakt) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (type, contact_id, pand_slug, klus_id, ontvanger, concept_onderwerp,
         concept_body, ACTIE_OPEN, _nu()),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_actie(conn: sqlite3.Connection, actie_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM acties WHERE id = ?", (actie_id,)).fetchone()


def lijst_acties(
    conn: sqlite3.Connection, pand_slugs: list[str] | None = None, status: str = ACTIE_OPEN
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM acties WHERE status = ?"
    params: list = [status]
    if pand_slugs is not None:
        sql += f" AND pand_slug IN ({_plaatshouders(pand_slugs)})"
        params.extend(pand_slugs)
    sql += " ORDER BY aangemaakt DESC, id DESC"
    return conn.execute(sql, params).fetchall()


def werk_actie_concept_bij(
    conn: sqlite3.Connection, actie_id: int, concept_onderwerp: str | None, concept_body: str
) -> None:
    """Jij kunt het AI-concept aanpassen voor je het goedkeurt."""
    conn.execute(
        "UPDATE acties SET concept_onderwerp = ?, concept_body = ? WHERE id = ?",
        (concept_onderwerp, concept_body, actie_id),
    )
    conn.commit()


def zet_actie_status(conn: sqlite3.Connection, actie_id: int, status: str) -> None:
    verzonden = _nu() if status == ACTIE_VERZONDEN else None
    conn.execute(
        "UPDATE acties SET status = ?, "
        "verzonden_op = CASE WHEN ? IS NOT NULL THEN ? ELSE verzonden_op END WHERE id = ?",
        (status, verzonden, verzonden, actie_id),
    )
    conn.commit()


def tel_open_acties(conn: sqlite3.Connection, pand_slugs: list[str] | None = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM acties WHERE status = ?"
    params: list = [ACTIE_OPEN]
    if pand_slugs is not None:
        sql += f" AND pand_slug IN ({_plaatshouders(pand_slugs)})"
        params.extend(pand_slugs)
    return int(conn.execute(sql, params).fetchone()["n"])


# --- hulp -------------------------------------------------------------------

def _plaatshouders(waarden) -> str:
    """"?, ?, ?" voor een IN-clausule. Bij een lege lijst een clausule die
    gegarandeerd niets matcht (zodat 'geen toegang' => geen resultaten)."""
    n = len(list(waarden))
    return ", ".join("?" * n) if n else "NULL"
