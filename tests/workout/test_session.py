"""Unit tests for WorkoutSession aggregation, gap tracking and timeline fusion."""

from __future__ import annotations

import pytest

from miband_monitor.workout import (
    STATE_FINISHED,
    STATE_GAP_FILLING,
    STATE_RECONNECTING,
    STATE_STREAMING,
    WorkoutProfile,
    WorkoutSession,
)


def test_session_filters_invalid_hr_and_tracks_zones_and_kcal() -> None:
    profile = WorkoutProfile(age=20, weight_kg=70.0, sex="male", hr_max=200)
    session = WorkoutSession(profile, started_at=1000.0)

    bad = session.record_heart_rate(255, ts=1001.0)
    assert bad["accepted"] is False
    assert session.record_heart_rate(0, ts=1002.0)["accepted"] is False

    # Valid samples spaced by 30 s at 150 BPM -> Zone 3 (Aerobic, 75% of 200)
    assert session.record_heart_rate(150, ts=1005.0)["accepted"] is True
    res = session.record_heart_rate(150, ts=1035.0)
    assert res["accepted"] is True
    assert res["zone"] == (3, "Aerobic")

    # Disconnect resets inter-sample dt integration so gap time is not billed to kcal
    session.on_disconnect(ts=1040.0)
    assert session.snapshot()["state"] == STATE_RECONNECTING
    session.record_heart_rate(170, ts=1200.0)

    snap = session.snapshot()
    assert snap["heart_rate"]["valid_count"] == 3
    assert snap["heart_rate"]["filtered_count"] == 2
    assert snap["heart_rate"]["min"] == 150
    assert snap["heart_rate"]["max"] == 170
    zones = {z["zone"]: z["seconds"] for z in snap["zones"]}
    assert zones[3] == pytest.approx(30.0)
    assert snap["calories"]["estimated_hr_kcal"] > 5.0


def test_session_gap_classification_and_timeline_fusion() -> None:
    session = WorkoutSession(started_at=1000.0, gap_fill_min_seconds=60.0)
    session.record_heart_rate(130, ts=1010.0)

    # Short disconnect (< 60 s) skips ACTIVITY gap-fill
    session.on_disconnect(ts=1020.0)
    short_gap = session.on_reconnect(ts=1035.0)
    assert short_gap is not None
    assert short_gap["status"] == "short_skip"
    assert session.snapshot()["state"] == STATE_STREAMING

    # Long disconnect (>= 60 s) enters gap-filling and accepts band history points
    session.on_disconnect(ts=1050.0)
    long_gap = session.on_reconnect(ts=1170.0)
    assert long_gap is not None
    assert long_gap["status"] == "pending"
    assert session.snapshot()["state"] == STATE_GAP_FILLING

    added = session.ingest_gap_fill(
        [
            {"ts": 1080.0, "heart_rate": 138, "steps": 90, "intensity": 40, "kind": 1},
            {"ts": 1140.0, "heart_rate": 0, "steps": 0},  # invalid HR ignored
            {"ts": 1141.0, "heart_rate": 144, "steps": 95, "intensity": 42, "kind": 1},
        ],
        gap_start=long_gap["start_ts"],
        gap_end=long_gap["end_ts"],
    )
    assert added == 2
    session.record_heart_rate(148, ts=1180.0)

    timeline = session.fused_timeline()
    assert [p["source"] for p in timeline] == ["live", "gap_fill", "gap_fill", "live"]
    assert [p["bpm"] for p in timeline] == [130, 138, 144, 148]

    session.record_steps({"steps": 2000, "distance_meters": 1400, "calories": 100}, ts=1010.0)
    session.record_steps({"steps": 2350, "distance_meters": 1680, "calories": 124}, ts=1180.0)
    session.record_battery(82, ts=1180.0)

    summary = session.finish(ts=1200.0)
    assert summary["state"] == STATE_FINISHED
    assert summary["active"] is False
    assert summary["elapsed_seconds"] == pytest.approx(200.0)
    assert summary["steps"]["net_steps"] == 350
    assert summary["steps"]["net_band_kcal"] == 24
    assert summary["battery_pct"] == 82
    assert summary["reconnect_count"] == 2
    assert summary["gap_filled_count"] == 2
