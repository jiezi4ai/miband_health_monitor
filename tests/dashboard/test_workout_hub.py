"""Tests for TelemetryHub workout snapshots/SSE and page asset composition."""

from __future__ import annotations

import asyncio

import pytest

from miband_monitor.dashboard import METRIC_KINDS, TelemetryHub, page


def test_compose_page_inlines_workout_script() -> None:
    html = page.compose_page()
    assert page.WORKOUT_SCRIPT_TOKEN not in html
    assert "workoutPanel" in html
    assert "MiBandWorkout" in html


@pytest.mark.asyncio
async def test_hub_publish_workout_fans_out_without_changing_metric_kinds() -> None:
    hub = TelemetryHub()
    assert "workout" not in METRIC_KINDS
    assert "workout" not in hub.snapshot()

    queue = hub.subscribe()
    try:
        sample_summary = {
            "active": True,
            "state": "streaming",
            "elapsed_seconds": 12.5,
            "steps": {"net_steps": 45, "net_distance_m": 32, "net_band_kcal": 2},
            "calories": {"estimated_hr_kcal": 3.4, "band_kcal": 2},
            "battery_pct": 88,
            "zones": [],
            "timeline": [],
        }
        hub.publish_workout(sample_summary, timestamp=1000.0)
        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event["kind"] == "workout"
        assert event["workout"]["battery_pct"] == 88

        snap = hub.snapshot()
        assert snap["workout"]["state"] == "streaming"
        assert set(snap["series"]) == set(METRIC_KINDS)
    finally:
        hub.unsubscribe(queue)
