"""Regressions found while calibrating against seven Zepp Life nights.

Both failures were silent: the numbers looked plausible, so nothing complained.
"""

from __future__ import annotations

import sqlite3

import pytest
from datetime import datetime
from types import SimpleNamespace

from miband_monitor.sleep.calibration import find_session
from miband_monitor.sleep.samples import load_samples
from tests.sleep.support import _seed_database, sample


def _session(start: datetime, minutes: int) -> SimpleNamespace:
    start_ts = start.timestamp()
    return SimpleNamespace(
        start=start_ts,
        end=start_ts + (minutes - 1) * 60,
        samples=[{"ts": start_ts + i * 60} for i in range(minutes)],
    )


def test_find_session_prefers_the_night_over_an_earlier_nap():
    """A date holds naps too, and the first session of the day is rarely the night.

    Returning the nap compared 60 band minutes against a 483-minute reference and
    made every model look broken.
    """
    day = datetime(2026, 11, 13)
    nap = _session(day.replace(hour=12, minute=28), 60)
    night = _session(day.replace(hour=22, minute=15), 480)
    result = {"_sessions": [nap, night]}

    assert find_session(result, "2026-11-13") is night
    assert find_session(result, "2026-11-13", ["22:24", "06:27"]) is night


def test_find_session_follows_the_app_window_when_it_points_elsewhere():
    """With an explicit window the overlap decides, not the session length."""
    day = datetime(2026, 11, 13)
    nap = _session(day.replace(hour=12, minute=28), 60)
    night = _session(day.replace(hour=22, minute=15), 480)
    result = {"_sessions": [nap, night]}

    assert find_session(result, "2026-11-13", ["12:30", "13:20"]) is nap


def test_find_session_returns_none_when_the_window_covers_nothing():
    day = datetime(2026, 11, 13)
    night = _session(day.replace(hour=22, minute=15), 480)
    assert find_session({"_sessions": [night]}, "2026-11-13", ["03:00", "04:00"]) is None


def test_duplicate_minutes_are_rejected_by_the_schema(tmp_path):
    """Repeated syncs left 1432 duplicate minutes in the real database.

    Two rows for one minute doubled the in-bed total (1002 minutes for a 500-minute
    night) and inflated every downstream aggregate. Since schema v3 the unique
    index on ``ts`` refuses the second row outright, and ``load_samples`` keeps its
    own de-duplication as a second line of defence.
    """
    db = _seed_database(tmp_path, [sample(0), sample(1), sample(2)])
    conn = sqlite3.connect(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO activity_history (ts, iso_time, kind, intensity, steps, "
                "heart_rate, unknown1, sleep, deep_sleep, rem_sleep) "
                "SELECT ts, iso_time, kind, intensity, steps, heart_rate, unknown1, "
                "sleep, deep_sleep, rem_sleep FROM activity_history"
            )
    finally:
        conn.close()

    rows = load_samples(db, include_scores=True)
    assert len(rows) == 3
    assert len({row["ts"] for row in rows}) == 3
