"""SQLite schema, JSONL filenames and SQL statements for telemetry storage.

This module is the single source of truth for the on-disk format. It contains no
I/O and has no project dependencies beyond configuration defaults, so analysis
packages (sleep, offline dashboard) can import table/column names without
starting a writer thread.

Durability contract -- do not change without migrating existing data:

* JSONL files are append-only, one JSON object per line, named after the stream.
* SQLite lives in one WAL database (data/mi_band.db) with one table per stream,
  indexed by ts (Unix epoch seconds, UTC).
* Sleep SpO2 (fetch type 0x26) has its own JSONL file and SQLite table. It is a
  night-long dense stream and must never be mixed with point-measurement
  spo2 rows.

The SQLite layout carries a monotonically increasing ``schema_version`` in
``PRAGMA user_version`` (:data:`SCHEMA_VERSION`). ``open_database`` applies the
idempotent ``_SCHEMA`` and then :func:`migrate`, which advances an older (or
unversioned legacy) database step by step and refuses to open a database written
by a newer schema than this code understands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, List, Tuple

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module I/O-free
    import sqlite3

from ..config.defaults import DEFAULT_DB_FILENAME
from .stress_schema import STRESS_COLUMNS, STRESS_DDL, STRESS_INSERT_SQL, STRESS_TABLE, migrate_v2_to_v3
from .summary_schema import ACTIVITY_SUMMARY_COLUMNS, ACTIVITY_SUMMARY_TABLE, SUMMARY_DDL, SUMMARY_INSERT_SQL, migrate_v1_to_v2

#: Accepted --storage backend names, in the order shown by the CLI help.
STORAGE_BACKENDS: Tuple[str, ...] = ("jsonl", "sqlite", "both", "none")

#: JSONL filename for each record stream, in writer/initialisation order.
JSONL_FILENAMES: Dict[str, str] = {
    "heart_rate": "heart_rate.jsonl",
    "steps": "steps.jsonl",
    "imu": "imu.jsonl",
    "spo2": "spo2.jsonl",
    "activity_history": "activity_history.jsonl",
    # Sleep SpO2 (0x26): own JSONL and table, never mixed with spot-check spo2.
    "spo2_sleep": "spo2_sleep.jsonl",
    "activity_summary": "activity_summary.jsonl",
    "stress": "stress.jsonl",
}

#: Record kinds handled by TelemetryStore.
RECORD_KINDS: Tuple[str, ...] = tuple(JSONL_FILENAMES)

#: SQLite database filename created inside the output directory.
DB_FILENAME: str = DEFAULT_DB_FILENAME

# ---------------------------------------------------------------------------
# Schema versioning (PRAGMA user_version)
# ---------------------------------------------------------------------------
#: Current on-disk schema version. Bump this whenever ``_SCHEMA`` or a column
#: layout changes, and append a matching step to :data:`MIGRATIONS`.
SCHEMA_VERSION: int = 3


class SchemaVersionError(RuntimeError):
    """Raised when a database cannot be opened at the current schema version."""


def get_schema_version(conn: "sqlite3.Connection") -> int:
    """Read the database's ``user_version`` (0 means legacy/unversioned)."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _migrate_legacy_to_v1(conn: "sqlite3.Connection") -> None:
    """Adopt a pre-versioning database (user_version 0).

    ``executescript(_SCHEMA)`` already reconciled every table (they all use
    ``IF NOT EXISTS``), so adoption only stamps the version. **No rows are
    dropped or rewritten.**
    """
    return None


#: Ordered migration steps: key N upgrades a version-N database to version N+1.
#: Each callable receives an open connection and may execute DDL/DML. Add new
#: steps here (and bump SCHEMA_VERSION) rather than editing historical steps.
MIGRATIONS: Dict[int, Callable[["sqlite3.Connection"], None]] = {
    0: _migrate_legacy_to_v1,
    1: migrate_v1_to_v2,
    2: migrate_v2_to_v3,
}

# ---------------------------------------------------------------------------
# Table and column names (shared by the writer, readers and CSV exporter)
# ---------------------------------------------------------------------------
HEART_RATE_TABLE = "heart_rate"
HEART_RATE_COLUMNS = ("id", "ts", "iso_time", "bpm")

STEPS_TABLE = "steps"
STEPS_COLUMNS = ("id", "ts", "iso_time", "steps", "distance_m", "calories")

IMU_TABLE = "imu"
IMU_COLUMNS = (
    "id",
    "ts",
    "iso_time",
    "sensor_type",
    "sequence",
    "sample_index",
    "x_raw",
    "y_raw",
    "z_raw",
    "ax_g",
    "ay_g",
    "az_g",
    "ax_ms2",
    "ay_ms2",
    "az_ms2",
)

SPO2_TABLE = "spo2"
SPO2_COLUMNS = ("id", "ts", "iso_time", "spo2", "auto_measure")

ACTIVITY_HISTORY_TABLE = "activity_history"
ACTIVITY_HISTORY_COLUMNS = (
    "id",
    "ts",
    "iso_time",
    "kind",
    "intensity",
    "steps",
    "heart_rate",
    "unknown1",
    "sleep",
    "deep_sleep",
    "rem_sleep",
)

SPO2_SLEEP_TABLE = "spo2_sleep"
SPO2_SLEEP_COLUMNS = (
    "id",
    "ts",
    "iso_time",
    "spo2",
    "duration",
    "spo2_high",
    "spo2_low",
    "signal_quality",
    "extend",
)

#: CSV export column order per table (must match _SCHEMA); lists for the
#: historical export_csv.TABLE_COLUMNS mapping.
TABLE_COLUMNS: Dict[str, List[str]] = {
    HEART_RATE_TABLE: list(HEART_RATE_COLUMNS), STEPS_TABLE: list(STEPS_COLUMNS),
    IMU_TABLE: list(IMU_COLUMNS), SPO2_TABLE: list(SPO2_COLUMNS),
    ACTIVITY_HISTORY_TABLE: list(ACTIVITY_HISTORY_COLUMNS),
    SPO2_SLEEP_TABLE: list(SPO2_SLEEP_COLUMNS),
    ACTIVITY_SUMMARY_TABLE: list(ACTIVITY_SUMMARY_COLUMNS),
    STRESS_TABLE: list(STRESS_COLUMNS),
}

# ---------------------------------------------------------------------------
# SQLite schema (executed once on writer startup; CREATE ... IF NOT EXISTS)
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS heart_rate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    iso_time TEXT NOT NULL,
    bpm INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    iso_time TEXT NOT NULL,
    steps INTEGER NOT NULL,
    distance_m INTEGER NOT NULL,
    calories INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS imu (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    iso_time TEXT NOT NULL,
    sensor_type INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    sample_index INTEGER NOT NULL,
    x_raw INTEGER NOT NULL,
    y_raw INTEGER NOT NULL,
    z_raw INTEGER NOT NULL,
    ax_g REAL NOT NULL,
    ay_g REAL NOT NULL,
    az_g REAL NOT NULL,
    ax_ms2 REAL NOT NULL,
    ay_ms2 REAL NOT NULL,
    az_ms2 REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_heart_rate_ts ON heart_rate(ts);
CREATE INDEX IF NOT EXISTS idx_steps_ts ON steps(ts);
CREATE INDEX IF NOT EXISTS idx_imu_ts ON imu(ts);

CREATE TABLE IF NOT EXISTS spo2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    iso_time TEXT NOT NULL,
    spo2 INTEGER NOT NULL,
    auto_measure INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS activity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    iso_time TEXT NOT NULL,
    kind INTEGER NOT NULL,
    intensity INTEGER NOT NULL,
    steps INTEGER NOT NULL,
    heart_rate INTEGER NOT NULL,
    unknown1 INTEGER NOT NULL DEFAULT 0,
    sleep INTEGER NOT NULL DEFAULT 0,
    deep_sleep INTEGER NOT NULL DEFAULT 0,
    rem_sleep INTEGER NOT NULL DEFAULT 0
);

-- Sleep SpO2 (fetch type 0x26) lives in its OWN table: it is a dense
-- night-long stream, not a point measurement, and must never be mixed with
-- ``spo2``. The four trailing byte groups stay as JSON text because their
-- semantics are still unconfirmed (see band_history module docstring).
CREATE TABLE IF NOT EXISTS spo2_sleep (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    iso_time TEXT NOT NULL,
    spo2 INTEGER NOT NULL,
    duration INTEGER NOT NULL DEFAULT 0,
    spo2_high TEXT NOT NULL DEFAULT '[]',
    spo2_low TEXT NOT NULL DEFAULT '[]',
    signal_quality TEXT NOT NULL DEFAULT '[]',
    extend TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_spo2_ts ON spo2(ts);
CREATE INDEX IF NOT EXISTS idx_activity_history_ts ON activity_history(ts);
CREATE INDEX IF NOT EXISTS idx_spo2_sleep_ts ON spo2_sleep(ts);
""" + SUMMARY_DDL + STRESS_DDL


def migrate(conn: "sqlite3.Connection") -> int:
    """Advance *conn*'s schema to :data:`SCHEMA_VERSION`, returning the version.

    Call after applying the idempotent :data:`_SCHEMA`. Legacy/unversioned
    databases (``user_version == 0``) are adopted without touching their rows;
    unknown intermediate versions raise rather than silently corrupting data.
    A database newer than this code is refused so an older build never rewrites
    it with an incompatible layout.
    """
    version = get_schema_version(conn)
    if version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"database schema v{version} is newer than supported v{SCHEMA_VERSION}"
        )
    while version < SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:  # pragma: no cover - guard against a forgotten step
            raise SchemaVersionError(f"no migration registered from v{version}")
        step(conn)
        version += 1
        conn.execute(f"PRAGMA user_version = {version}")
    return version


#: Prepared INSERT statement per record kind (column order matches the payload
#: tuples built by miband_monitor.storage.sqlite).
_INSERT_SQL = {
    "heart_rate": "INSERT INTO heart_rate (ts, iso_time, bpm) VALUES (?, ?, ?)",
    "steps": (
        "INSERT INTO steps (ts, iso_time, steps, distance_m, calories) "
        "VALUES (?, ?, ?, ?, ?)"
    ),
    "imu": (
        "INSERT INTO imu (ts, iso_time, sensor_type, sequence, sample_index, "
        "x_raw, y_raw, z_raw, ax_g, ay_g, az_g, ax_ms2, ay_ms2, az_ms2) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    ),
    "spo2": (
        "INSERT INTO spo2 (ts, iso_time, spo2, auto_measure) VALUES (?, ?, ?, ?)"
    ),
    "activity_history": (
        "INSERT OR IGNORE INTO activity_history (ts, iso_time, kind, intensity, steps, "
        "heart_rate, unknown1, sleep, deep_sleep, rem_sleep) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    ),
    "spo2_sleep": (
        "INSERT INTO spo2_sleep (ts, iso_time, spo2, duration, spo2_high, "
        "spo2_low, signal_quality, extend) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    ),
    "activity_summary": SUMMARY_INSERT_SQL,
    "stress": STRESS_INSERT_SQL,
}
