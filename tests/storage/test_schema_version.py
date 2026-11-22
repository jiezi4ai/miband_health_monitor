"""B-2: schema_version stamping, legacy adoption and forward-version refusal."""

from __future__ import annotations

import sqlite3

import pytest

from miband_monitor.storage.schema import (
    MIGRATIONS,
    SCHEMA_VERSION,
    SchemaVersionError,
    _SCHEMA,
    get_schema_version,
    migrate,
)
from miband_monitor.storage.sqlite import open_database


def test_schema_version_is_positive_and_migration_steps_are_contiguous():
    assert isinstance(SCHEMA_VERSION, int) and SCHEMA_VERSION >= 1
    # Every version below the current one must have a registered step.
    for version in range(SCHEMA_VERSION):
        assert version in MIGRATIONS, f"missing migration from v{version}"


def test_fresh_database_is_stamped_with_current_version(tmp_path):
    conn = open_database(tmp_path / "fresh.db")
    try:
        assert get_schema_version(conn) == SCHEMA_VERSION
    finally:
        conn.close()


def test_open_is_idempotent_and_preserves_version(tmp_path):
    path = tmp_path / "fresh.db"
    conn = open_database(path)
    conn.close()
    conn = open_database(path)  # reopen an already-versioned database
    try:
        assert get_schema_version(conn) == SCHEMA_VERSION
        assert migrate(conn) == SCHEMA_VERSION
    finally:
        conn.close()


def test_legacy_unversioned_database_is_adopted_without_data_loss(tmp_path):
    """A pre-versioning DB (user_version 0) keeps every row when opened."""
    path = tmp_path / "legacy.db"
    raw = sqlite3.connect(path)
    try:
        raw.executescript(_SCHEMA)
        raw.execute(
            "INSERT INTO heart_rate (ts, iso_time, bpm) VALUES (?, ?, ?)",
            (1000.0, "1970-01-01T00:16:40+00:00", 72),
        )
        raw.commit()
        assert get_schema_version(raw) == 0
    finally:
        raw.close()

    conn = open_database(path)  # adopts v0 -> v1 in place
    try:
        assert get_schema_version(conn) == SCHEMA_VERSION
        rows = conn.execute("SELECT bpm FROM heart_rate").fetchall()
        assert rows == [(72,)]
    finally:
        conn.close()


def test_database_from_newer_schema_is_refused(tmp_path):
    path = tmp_path / "future.db"
    raw = sqlite3.connect(path)
    try:
        raw.executescript(_SCHEMA)
        raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(SchemaVersionError, match="newer than supported"):
        open_database(path)


def test_v1_database_upgrades_all_the_way_to_v3(tmp_path):
    path = tmp_path / "v1.db"
    raw = sqlite3.connect(path)
    try:
        raw.execute(
            "CREATE TABLE heart_rate (id INTEGER PRIMARY KEY, ts REAL, iso_time TEXT, bpm INTEGER)"
        )
        raw.execute("PRAGMA user_version = 1")
        raw.commit()
    finally:
        raw.close()

    conn = open_database(path)
    try:
        assert get_schema_version(conn) == SCHEMA_VERSION == 3
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"activity_summary", "stress"} <= tables
    finally:
        conn.close()


def test_v3_migration_repairs_duplicate_activity_minutes(tmp_path):
    """The v2 -> v3 step drops duplicate minutes and makes a recurrence impossible."""
    path = tmp_path / "v2.db"
    raw = sqlite3.connect(path)
    try:
        raw.executescript(
            "CREATE TABLE activity_history (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "ts REAL NOT NULL, iso_time TEXT NOT NULL, kind INTEGER NOT NULL, "
            "intensity INTEGER NOT NULL, steps INTEGER NOT NULL, heart_rate INTEGER NOT NULL, "
            "unknown1 INTEGER NOT NULL DEFAULT 0, sleep INTEGER NOT NULL DEFAULT 0, "
            "deep_sleep INTEGER NOT NULL DEFAULT 0, rem_sleep INTEGER NOT NULL DEFAULT 0);"
        )
        raw.executemany(
            "INSERT INTO activity_history (ts, iso_time, kind, intensity, steps, heart_rate) "
            "VALUES (?, '', 240, 0, 0, 60)",
            [(1000.0,), (1000.0,), (1060.0,)],
        )
        raw.execute("PRAGMA user_version = 2")
        raw.commit()
    finally:
        raw.close()

    conn = open_database(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM activity_history").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO activity_history (ts, iso_time, kind, intensity, steps, heart_rate) "
                "VALUES (1000.0, '', 240, 0, 0, 60)"
            )
    finally:
        conn.close()
