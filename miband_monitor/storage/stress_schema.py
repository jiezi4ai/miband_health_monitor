"""Stress table (fetch type 0x13) and the v2 -> v3 migration.

Kept out of ``schema.py`` for the same reason as ``summary_schema.py``: that
module sits on the 300-line budget, and the DDL for one stream plus its migration
is the natural unit to move.

The table is keyed by ``ts`` (one reading per minute) with a **unique** index, so
re-syncing an overlapping window replaces instead of duplicating. That matters
here more than elsewhere: stress arrives as a dense per-minute stream, so a
double fetch would otherwise add thousands of phantom rows.
"""

from __future__ import annotations

import sqlite3

STRESS_TABLE = "stress"

STRESS_COLUMNS = ("id", "ts", "iso_time", "stress", "band")

STRESS_DDL = """
CREATE TABLE IF NOT EXISTS stress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    iso_time TEXT NOT NULL,
    stress INTEGER NOT NULL,
    band TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stress_ts ON stress(ts);
"""

STRESS_INSERT_SQL = (
    "INSERT OR REPLACE INTO stress (ts, iso_time, stress, band) VALUES (?, ?, ?, ?)"
)


def migrate_v2_to_v3(conn: "sqlite3.Connection") -> None:
    """Add the stress table, then repair the duplicate-minute hole in activity_history.

    The duplicates were a real defect: repeated syncs left 1432 rows sharing a
    ``ts``, which doubled in-bed minutes for two nights. The reader now collapses
    them, but leaving them in place keeps the file growing and keeps every CSV
    export wrong, so the first-inserted row per minute is kept (re-syncs deliver
    identical band data) and the rest dropped. The unique index added afterwards
    makes a recurrence impossible.
    """
    conn.executescript(STRESS_DDL)
    conn.execute(
        "DELETE FROM activity_history WHERE id NOT IN "
        "(SELECT MIN(id) FROM activity_history GROUP BY ts)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_history_ts_unique "
        "ON activity_history(ts)"
    )
