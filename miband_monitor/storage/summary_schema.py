"""SQLite layout for band-side workout summaries (0x05, B-12).

Kept out of ``storage/schema.py`` so that module stays under the 300-line
budget.  The table is created idempotently by the base schema and again by the
v1 -> v2 migration, so both fresh and upgraded databases get it.

Key choice: ``(ts, end_ts)`` is unique and the insert uses ``OR REPLACE``.  A
summary is identified by its workout start/end pair, so re-syncing the same
record (or a retry after a partial write) updates instead of duplicating it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    import sqlite3

ACTIVITY_SUMMARY_TABLE = "activity_summary"
ACTIVITY_SUMMARY_COLUMNS = (
    "id",
    "ts",
    "iso_time",
    "end_ts",
    "duration_s",
    "kind_code",
    "kind_name",
    "steps",
    "active_seconds",
    "calories",
    "distance_m",
    "average_hr",
    "max_hr",
    "min_hr",
    "average_pace_s_km",
    "version",
    "has_gps",
)

SUMMARY_DDL = """
CREATE TABLE IF NOT EXISTS activity_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    iso_time TEXT NOT NULL,
    end_ts REAL NOT NULL DEFAULT 0,
    duration_s INTEGER NOT NULL DEFAULT 0,
    kind_code INTEGER NOT NULL DEFAULT 0,
    kind_name TEXT NOT NULL DEFAULT '',
    steps INTEGER NOT NULL DEFAULT 0,
    active_seconds INTEGER NOT NULL DEFAULT 0,
    calories REAL NOT NULL DEFAULT 0,
    distance_m REAL NOT NULL DEFAULT 0,
    average_hr INTEGER NOT NULL DEFAULT 0,
    max_hr INTEGER NOT NULL DEFAULT 0,
    min_hr INTEGER NOT NULL DEFAULT 0,
    average_pace_s_km INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 0,
    has_gps INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_summary_key
    ON activity_summary(ts, end_ts);
"""

SUMMARY_INSERT_SQL = (
    "INSERT OR REPLACE INTO activity_summary (ts, iso_time, end_ts, duration_s, "
    "kind_code, kind_name, steps, active_seconds, calories, distance_m, "
    "average_hr, max_hr, min_hr, average_pace_s_km, version, has_gps) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def migrate_v1_to_v2(conn: "sqlite3.Connection") -> None:
    """Create the workout-summary table for a database stamped v1."""
    conn.executescript(SUMMARY_DDL)


__all__ = [
    "ACTIVITY_SUMMARY_COLUMNS",
    "ACTIVITY_SUMMARY_TABLE",
    "SUMMARY_DDL",
    "SUMMARY_INSERT_SQL",
    "migrate_v1_to_v2",
]
