"""B-14: battery as a shared hub series covering default (non-workout) sessions."""

from __future__ import annotations

import asyncio
import json

import pytest

from dashboard import BATTERY_KIND, EVENT_SERIES_KINDS, METRIC_KINDS, TelemetryHub
from miband_monitor.dashboard import page
from miband_monitor.cli import workout_runner


# ---------------------------------------------------------------------------
# hub series
# ---------------------------------------------------------------------------
def test_battery_is_a_series_without_joining_db_metric_kinds():
    hub = TelemetryHub(max_points=3)
    assert BATTERY_KIND in EVENT_SERIES_KINDS
    assert "battery" not in METRIC_KINDS
    # Lazy creation: no battery read yet -> snapshot has the pre-B-14 shape.
    assert set(hub.snapshot()["series"]) == set(METRIC_KINDS)
    assert hub.history("battery") == []

    for level in (91, 88, 84, 80):
        hub.publish_battery(level, timestamp=1000.0 + level)
    snap = hub.snapshot()
    assert snap["counts"]["battery"] == 4
    assert [row["level"] for row in snap["series"]["battery"]] == [88, 84, 80]
    assert snap["latest"]["battery"]["level"] == 80
    assert [row["level"] for row in hub.history("battery", limit=2)] == [84, 80]
    with pytest.raises(ValueError, match="out of range"):
        hub.publish_battery(101)


def test_device_events_are_remembered_for_a_fresh_page():
    hub = TelemetryHub()
    hub.publish_event("device", {"state": "initialized", "busy_task": None, "reconnect_count": 1})
    snap = hub.snapshot()
    assert snap["event_latest"]["device"]["state"] == "initialized"
    assert snap["event_latest"]["device"]["reconnect_count"] == 1
    assert "device" not in snap["series"]  # out-of-band, not a metric


async def test_battery_fans_out_over_sse():
    hub = TelemetryHub()
    hub.attach_loop(asyncio.get_running_loop())
    queue = hub.subscribe()
    try:
        hub.publish_battery(76)
        record = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert record["kind"] == "battery" and record["level"] == 76
    finally:
        hub.unsubscribe(queue)


# ---------------------------------------------------------------------------
# battery probe path
# ---------------------------------------------------------------------------
class _FakeClient:
    def __init__(self, level=77):
        self._level = level

    async def read_battery_level(self):
        return self._level

    async def wait_until_disconnected(self):
        await asyncio.sleep(10)


class _FakeWorkout:
    def __init__(self):
        self.levels = []

    def record_battery(self, level):
        self.levels.append(level)

    def snapshot(self, *, timeline_limit=300):
        return {"battery_pct": self.levels[-1] if self.levels else None, "timeline": []}


async def test_battery_probe_works_without_a_workout():
    hub = TelemetryHub()
    level = await workout_runner.run_battery_probe(_FakeClient(66), hub=hub)
    assert level == 66
    assert hub.snapshot()["latest"]["battery"]["level"] == 66
    assert "workout" not in hub.snapshot()


async def test_battery_probe_still_feeds_the_workout_snapshot():
    hub = TelemetryHub()
    workout = _FakeWorkout()
    level = await workout_runner.run_battery_probe(_FakeClient(55), workout, hub=hub)
    assert level == 55 and workout.levels == [55]
    assert hub.snapshot()["workout"]["battery_pct"] == 55
    assert hub.snapshot()["latest"]["battery"]["level"] == 55


async def test_default_session_polls_battery(monkeypatch):
    calls = []

    async def fake_probe(client, workout=None, *, hub=None):
        calls.append(workout)
        return 61

    monkeypatch.setattr(workout_runner, "run_battery_probe", fake_probe)
    outcome = await workout_runner.wait_session_with_battery(
        _FakeClient(), 0.03, None, battery_interval=0.01,
        hub=TelemetryHub(), wait_for_fn=asyncio.wait_for,
    )
    assert outcome == "timeout"
    assert calls and all(item is None for item in calls)


# ---------------------------------------------------------------------------
# page assets
# ---------------------------------------------------------------------------
def test_live_page_shows_battery_and_device_state():
    html = page.compose_page()
    assert 'id="battery"' in html and 'id="batteryChart"' in html
    assert 'id="deviceState"' in html
    assert "function applyDevice(" in html
    assert "event_latest" in html
    assert "series.battery" in html
