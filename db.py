"""SQLite laag voor de gewicht-tracker.

Opzet: `manual_entries` bevat alleen de dagen die je echt hebt ingevuld.
`daily_weights` is een afgeleide tabel met een waarde voor élke dag tussen
de eerste en de laatste meting, waarbij de dagen tussen twee metingen in
lineair worden geïnterpoleerd. Die tabel wordt na elke wijziging opnieuw
opgebouwd vanuit `manual_entries`, zodat hij nooit uit sync kan raken.
"""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "weight.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS manual_entries (
            date TEXT PRIMARY KEY,
            weight REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily_weights (
            date TEXT PRIMARY KEY,
            weight REAL NOT NULL,
            is_interpolated INTEGER NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def upsert_manual_weight(entry_date: date, weight: float) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO manual_entries (date, weight) VALUES (?, ?) "
        "ON CONFLICT(date) DO UPDATE SET weight = excluded.weight",
        (entry_date.isoformat(), weight),
    )
    conn.commit()
    _recompute_interpolation(conn)
    conn.close()


def bulk_upsert_manual_weights(entries: list[tuple[date, float]]) -> None:
    """Voor het importeren van veel metingen tegelijk (Excel-import):
    schrijft alle metingen weg en herberekent de interpolatie daarna
    precies één keer, in plaats van na elke losse meting."""
    conn = get_connection()
    conn.executemany(
        "INSERT INTO manual_entries (date, weight) VALUES (?, ?) "
        "ON CONFLICT(date) DO UPDATE SET weight = excluded.weight",
        [(d.isoformat(), w) for d, w in entries],
    )
    conn.commit()
    _recompute_interpolation(conn)
    conn.close()


def _recompute_interpolation(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT date, weight FROM manual_entries ORDER BY date"
    ).fetchall()
    conn.execute("DELETE FROM daily_weights")
    for i, row in enumerate(rows):
        d1 = date.fromisoformat(row["date"])
        w1 = row["weight"]
        conn.execute(
            "INSERT INTO daily_weights (date, weight, is_interpolated) VALUES (?, ?, 0)",
            (d1.isoformat(), w1),
        )
        if i + 1 < len(rows):
            next_row = rows[i + 1]
            d2 = date.fromisoformat(next_row["date"])
            w2 = next_row["weight"]
            span_days = (d2 - d1).days
            if span_days > 1:
                step = (w2 - w1) / span_days
                for k in range(1, span_days):
                    interp_date = d1 + timedelta(days=k)
                    interp_weight = round(w1 + step * k, 2)
                    conn.execute(
                        "INSERT INTO daily_weights (date, weight, is_interpolated) VALUES (?, ?, 1)",
                        (interp_date.isoformat(), interp_weight),
                    )
    conn.commit()


def get_all_daily_weights() -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, weight, is_interpolated FROM daily_weights ORDER BY date"
    ).fetchall()
    conn.close()
    return rows


def get_weight_for_date(target: date) -> dict | None:
    """Beste bekende waarde voor `target`.

    Ligt de datum binnen het bereik van metingen: exacte of geïnterpoleerde
    waarde uit daily_weights. Ligt hij ná de laatste meting (bijv. "vandaag"
    terwijl je dat nog niet hebt ingevuld): de laatste bekende waarde, met
    een vlag dat het een schatting is.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT date, weight, is_interpolated FROM daily_weights WHERE date = ?",
        (target.isoformat(),),
    ).fetchone()
    if row:
        conn.close()
        return {"date": row["date"], "weight": row["weight"], "is_estimate": bool(row["is_interpolated"])}

    last = conn.execute(
        "SELECT date, weight FROM daily_weights WHERE date < ? ORDER BY date DESC LIMIT 1",
        (target.isoformat(),),
    ).fetchone()
    conn.close()
    if last:
        return {"date": last["date"], "weight": last["weight"], "is_estimate": True}
    return None


def get_last_date_at_or_below(weight: float, before: date) -> dict | None:
    """Meest recente dag vóór `before` waarop het gewicht `weight` of lager was."""
    conn = get_connection()
    row = conn.execute(
        "SELECT date, weight FROM daily_weights WHERE date < ? AND weight <= ? "
        "ORDER BY date DESC LIMIT 1",
        (before.isoformat(), weight),
    ).fetchone()
    conn.close()
    if row:
        return {"date": row["date"], "weight": row["weight"]}
    return None


def get_years_with_data() -> list[int]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT substr(date, 1, 4) AS y FROM daily_weights ORDER BY y"
    ).fetchall()
    conn.close()
    return [int(r["y"]) for r in rows]
