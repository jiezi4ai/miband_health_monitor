"""Storage tests for the two non-minute-series tables: 0x05 summaries and 0x13 stress."""

import sqlite3

from storage import TelemetryStore

SUMMARY = {
    "ts": 1782879293.0,
    "end_ts": 1782880894.0,
    "duration_s": 1601,
    "kind_code": 1,
    "kind_name": "outdoor_running",
    "steps": 4351,
    "active_seconds": 1597,
    "calories": 359.975,
    "distance_m": 3211.467,
    "average_hr": 172,
    "max_hr": 187,
    "min_hr": None,
    "average_pace_s_per_km": 497,
    "version": 519,
    "has_gps": False,
}


def test_activity_summary_roundtrip_and_duplicate_pair_replacement(tmp_path):
    """0x05 summaries are keyed by (start, end): a retry replaces, not duplicates."""
    with TelemetryStore(tmp_path, backend="both") as store:
        store.record_activity_summary(SUMMARY)
        store.record_activity_summary({**SUMMARY, "steps": 4400})

    conn = sqlite3.connect(tmp_path / "mi_band.db")
    try:
        rows = conn.execute(
            "SELECT steps, average_hr, max_hr, kind_name FROM activity_summary"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [(4400, 172, 187, "outdoor_running")]
    assert (tmp_path / "activity_summary.jsonl").exists()


def test_stress_readings_replace_the_same_minute(tmp_path):
    """0x13 is one byte per minute: a re-sync must update, not duplicate."""
    with TelemetryStore(tmp_path, backend="both") as store:
        for stress in (41, 55):
            store.record_stress({"ts": 1782879300.0, "stress": stress, "band": "mild"})
        store.record_stress({"ts": 1782879360.0, "stress": 12, "band": "relaxed"})

    conn = sqlite3.connect(tmp_path / "mi_band.db")
    try:
        rows = conn.execute("SELECT ts, stress, band FROM stress ORDER BY ts").fetchall()
    finally:
        conn.close()
    assert rows == [(1782879300.0, 55, "mild"), (1782879360.0, 12, "relaxed")]
    assert (tmp_path / "stress.jsonl").exists()
