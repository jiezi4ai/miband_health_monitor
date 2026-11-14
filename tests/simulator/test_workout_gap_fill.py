"""Tests for targeted ACTIVITY gap-fill, CLI workout flags and end-to-end workout flow."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from miband_monitor.cli.args import parse_args
from miband_monitor.cli.callbacks import build_callbacks
from miband_monitor.cli.runner import run_monitor
from miband_monitor.dashboard import TelemetryHub
from miband_monitor.history import sync_history
from miband_monitor.simulator import FakeBleakScanner, SimulatedBand, simulated_factories
from miband_monitor.simulator.payloads import _activity_sample
from miband_monitor.storage import TelemetryStore, read_jsonl
from miband_monitor.workout import WorkoutProfile, WorkoutSession
from tests.support import AUTH_KEY_BYTES, KEY, MAC, connect_simulated_client


def test_workout_cli_arguments_and_validation() -> None:
    args = parse_args(
        [
            "--demo",
            "5",
            "--workout",
            "--age",
            "28",
            "--weight",
            "64.5",
            "--sex",
            "female",
            "--hr-max",
            "192",
            "--battery-interval",
            "120",
            "--gap-fill-min",
            "30",
        ]
    )
    assert args.workout is True
    assert args.age == 28
    assert args.weight == 64.5
    assert args.sex == "female"
    assert args.hr_max == 192
    assert args.battery_interval == 120.0
    assert args.gap_fill_min == 30.0

    with pytest.raises(SystemExit):
        parse_args(["--workout", "--age", "0"])
    with pytest.raises(SystemExit):
        parse_args(["--workout", "--weight", "-1"])


@pytest.mark.asyncio
async def test_sync_history_since_and_until_ts_filters_window() -> None:
    # Minute-aligned UTC timestamps strictly in the past so sync_history covers them cleanly.
    base = int((time.time() - 600) // 60) * 60
    band = SimulatedBand(
        auth_key=AUTH_KEY_BYTES,
        band_tz=timezone.utc,
        history_activity=[
            _activity_sample(base, steps=10, heart_rate=110),
            _activity_sample(base + 60, steps=25, heart_rate=135),
            _activity_sample(base + 120, steps=30, heart_rate=142),
            _activity_sample(base + 180, steps=5, heart_rate=95),
        ],
    )
    client = await connect_simulated_client(band)
    try:
        res = await sync_history(
            client,
            since_ts=base + 60,
            until_ts=base + 120,
            include_spo2=False,
            include_activity=True,
            band_tz=timezone.utc,
        )
        assert [s["heart_rate"] for s in res.activity] == [135, 142]
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_workout_reconnect_gap_fill_and_storage_separation(tmp_path) -> None:
    now_min = int(time.time() // 60) * 60
    band = SimulatedBand(
        auth_key=AUTH_KEY_BYTES,
        band_tz=timezone.utc,
        hr_values=(136, 142, 146),
        continuous_interval=0.03,
        disconnect_after=0.08,
        battery_level=78,
        history_activity=[
            _activity_sample(now_min - 120, steps=15, heart_rate=128),
            _activity_sample(now_min - 60, steps=40, heart_rate=141),
        ],
    )
    # Only drop on the first connection so session #2 completes duration cleanly.
    orig_on_connect = band.on_connect

    def _connect_once_drop(client):
        if band.connect_count >= 1:
            band.disconnect_after = None
        orig_on_connect(client)

    band.on_connect = _connect_once_drop  # type: ignore[method-assign]
    sim_factory, _ = simulated_factories(band)

    class _Scanner(FakeBleakScanner):
        default_address = MAC

    def _make(mac: str, key: str):
        from miband_monitor.ble import MiBand6Client

        return MiBand6Client(
            mac, key, client_factory=sim_factory, scanner_factory=_Scanner
        )

    store = TelemetryStore(tmp_path, backend="both")
    hub = TelemetryHub()
    workout = WorkoutSession(
        WorkoutProfile(age=30, weight_kg=70.0, sex="male"),
        started_at=now_min - 180.0,
        gap_fill_min_seconds=0.01,
    )
    callbacks = build_callbacks(store, hub, workout=workout)

    try:
        await run_monitor(
            MAC,
            KEY,
            duration=0.30,
            callbacks=callbacks,
            reconnect=True,
            reconnect_initial_delay=0.02,
            band_tz="UTC",
            workout=workout,
            hub=hub,
            battery_interval=5.0,
            client_factory=_make,
        )
    finally:
        store.close()

    summary = workout.finish()
    assert band.connect_count >= 2
    assert summary["reconnect_count"] >= 1
    assert summary["battery_pct"] == 78
    assert summary["gap_filled_count"] >= 1
    assert any(p["source"] == "gap_fill" for p in workout.fused_timeline())

    # Contract check: gap-fill samples go ONLY to activity_history, never heart_rate.
    activity_rows = read_jsonl(tmp_path / "activity_history.jsonl")
    hr_rows = read_jsonl(tmp_path / "heart_rate.jsonl")
    assert len(activity_rows) >= 1
    assert all(r["bpm"] in (136, 142, 146) for r in hr_rows)
