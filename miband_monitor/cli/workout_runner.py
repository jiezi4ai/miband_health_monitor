"""CLI supervisor helpers for --workout keepalive sessions."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Optional

from ..ble.client import StreamCallbacks
from ..config.security import secure_path
from ..dashboard import TelemetryHub
from ..history.sync import sync_history
from ..workout import (
    STATE_GAP_FILLING,
    STATE_STREAMING,
    WorkoutProfile,
    WorkoutSession,
)

logger = logging.getLogger("MiBand6Client")

_SSE_TIMELINE_LIMIT = 300


def build_workout_profile(args) -> WorkoutProfile:
    """Construct a validated :class:`WorkoutProfile` from parsed CLI args."""
    return WorkoutProfile(
        age=args.age,
        weight_kg=args.weight,
        sex=args.sex,
        hr_max=args.hr_max,
    )


async def backfill_activity_gap(
    client,
    workout: WorkoutSession,
    callbacks: StreamCallbacks,
    *,
    since_ts: float,
    until_ts: float,
    band_tz: Optional[str] = None,
) -> int:
    """Fetch targeted ACTIVITY (0x01) records for [since_ts, until_ts]."""
    try:
        result = await sync_history(
            client,
            since_ts=since_ts,
            until_ts=until_ts,
            include_spo2=False,
            include_activity=True,
            include_spo2_sleep=False,
            band_tz=band_tz,
            on_activity=callbacks.history_activity,
        )
        added = workout.ingest_gap_fill(
            result.activity,
            gap_start=since_ts,
            gap_end=until_ts,
            status="filled",
        )
        logger.info(
            "Workout ACTIVITY gap-fill fetched %d minute sample(s) (%d new HR point(s)).",
            len(result.activity),
            added,
        )
        return added
    except Exception as exc:
        logger.warning("Workout ACTIVITY gap-fill failed (continuing): %s", exc)
        workout.ingest_gap_fill(
            [], gap_start=since_ts, gap_end=until_ts, status="failed"
        )
        return 0


async def run_battery_probe(
    client,
    workout: Optional[WorkoutSession] = None,
    *,
    hub: Optional[TelemetryHub] = None,
) -> Optional[int]:
    """Read 0x2A19 best-effort and publish it as a battery series event.

    The workout snapshot remains a bonus when a workout session exists; the
    battery sample itself now belongs to the shared hub channel so a plain
    monitoring session shows it on the dashboard too (B-14).
    """
    read_fn = getattr(client, "read_battery_level", None)
    if not callable(read_fn):
        return None
    try:
        level = await read_fn()
    except Exception as exc:
        logger.debug("Best-effort battery probe error: %s", exc)
        return None
    if level is None:
        return None
    if hub is not None:
        try:
            hub.publish_battery(level)
        except Exception as exc:
            logger.debug("Battery event publish failed: %s", exc)
    if workout is not None:
        workout.record_battery(level)
        if hub is not None:
            hub.publish_workout(workout.snapshot(timeline_limit=_SSE_TIMELINE_LIMIT))
    return level


async def wait_session_with_battery(
    client,
    timeout: Optional[float],
    workout: Optional[WorkoutSession],
    *,
    battery_interval: float,
    hub: Optional[TelemetryHub] = None,
    wait_for_fn=asyncio.wait_for,
) -> str:
    """Wait until BLE link drops or *timeout* elapses, polling battery periodically.

    Battery probing is no longer gated on workout mode: a default session that
    has a dashboard hub still publishes one reading at start and then every
    ``battery_interval`` seconds.  With neither a workout nor a hub there is no
    consumer for the reading, so the historical wait-only path is kept.
    """
    if timeout is not None and timeout <= 0:
        return "timeout"
    if (workout is None and hub is None) or battery_interval <= 0:
        if timeout is None:
            await client.wait_until_disconnected()
            return "disconnected"
        try:
            await wait_for_fn(client.wait_until_disconnected(), timeout=timeout)
            return "disconnected"
        except asyncio.TimeoutError:
            return "timeout"

    await run_battery_probe(client, workout, hub=hub)
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            return "timeout"
        slice_wait = battery_interval if remaining is None else min(battery_interval, remaining)
        try:
            await wait_for_fn(client.wait_until_disconnected(), timeout=slice_wait)
            return "disconnected"
        except asyncio.TimeoutError:
            if deadline is not None and time.monotonic() >= deadline:
                return "timeout"
            await run_battery_probe(client, workout, hub=hub)


async def handle_workout_connected(
    client,
    workout: Optional[WorkoutSession],
    callbacks: StreamCallbacks,
    *,
    attempt: int,
    band_tz: Optional[str] = None,
    hub: Optional[TelemetryHub] = None,
) -> None:
    """Reconcile any prior disconnect gap before starting live streams."""
    if workout is None:
        return
    if attempt > 1 or getattr(workout, "_active_gap_start", None) is not None:
        gap = workout.on_reconnect()
        if gap is not None and gap["status"] == "pending":
            logger.info(
                "Backfilling ACTIVITY history for %.1fs disconnect gap...",
                gap["duration_s"],
            )
            if hub is not None:
                hub.publish_workout(workout.snapshot(timeline_limit=_SSE_TIMELINE_LIMIT))
            await backfill_activity_gap(
                client,
                workout,
                callbacks,
                since_ts=gap["start_ts"],
                until_ts=gap["end_ts"],
                band_tz=band_tz,
            )
    workout.mark_state(STATE_STREAMING)
    if hub is not None:
        hub.publish_workout(workout.snapshot(timeline_limit=_SSE_TIMELINE_LIMIT))


def handle_workout_disconnected(
    workout: Optional[WorkoutSession],
    *,
    hub: Optional[TelemetryHub] = None,
) -> None:
    """Record link loss on active workout state."""
    if workout is None:
        return
    workout.on_disconnect()
    if hub is not None:
        hub.publish_workout(workout.snapshot(timeline_limit=_SSE_TIMELINE_LIMIT))


async def handle_workout_finish(
    client,
    workout: Optional[WorkoutSession],
    callbacks: StreamCallbacks,
    *,
    band_tz: Optional[str] = None,
    hub: Optional[TelemetryHub] = None,
    reconcile: bool = True,
) -> None:
    """Stop active streams and pull final ACTIVITY records before disconnect."""
    if workout is None:
        return
    if reconcile and client is not None and getattr(client, "client", None) is not None:
        for stop_name in ("stop_heart_rate_stream", "stop_steps_stream", "stop_raw_sensor_stream"):
            stop_fn = getattr(client, stop_name, None)
            if callable(stop_fn):
                with contextlib.suppress(Exception):
                    await stop_fn()
        workout.mark_state(STATE_GAP_FILLING)
        if hub is not None:
            hub.publish_workout(workout.snapshot(timeline_limit=_SSE_TIMELINE_LIMIT))
        await backfill_activity_gap(
            client,
            workout,
            callbacks,
            since_ts=workout.started_at,
            until_ts=time.time(),
            band_tz=band_tz,
        )
    summary = workout.finish()
    if hub is not None:
        hub.publish_workout(summary)


def save_workout_summary(output_dir: str | Path, summary: dict) -> Path:
    """Persist workout summary report as JSON with restrictive permissions."""
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    secure_path(base, is_dir=True)
    target = base / "workout_summary.json"
    target.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    secure_path(target, is_dir=False)
    return target


def format_workout_summary(summary: dict) -> str:
    """Return a concise one-line human-readable workout summary."""
    hr = summary.get("heart_rate", {})
    steps = summary.get("steps", {})
    cal = summary.get("calories", {})
    return (
        f"Workout summary: duration={summary.get('elapsed_seconds', 0):.1f}s | "
        f"steps={steps.get('net_steps', 0)} | dist={steps.get('net_distance_m', 0)}m | "
        f"band_kcal={steps.get('net_band_kcal', 0)} | "
        f"hr_kcal={cal.get('estimated_hr_kcal', 0.0):.1f} | "
        f"hr_avg={hr.get('avg')} | hr_max={hr.get('max')} | "
        f"reconnects={summary.get('reconnect_count', 0)} | "
        f"gap_filled_mins={summary.get('gap_filled_count', 0)}"
    )
