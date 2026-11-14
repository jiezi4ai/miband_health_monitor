"""In-memory telemetry hub: ring buffers plus live SSE fan-out.

The hub is safe to feed from BLE notification callbacks. It only appends to
bounded deques and hands records to subscriber queues; when a callback comes
from a non-asyncio thread it schedules the fan-out on the attached event loop.
Slow subscribers are dropped (their bounded queue is full) rather than blocking
the BLE event loop.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from ..storage.readers import utc_iso
from .constants import DEFAULT_MAX_POINTS, DEFAULT_SNAPSHOT_POINTS, METRIC_KINDS, SSE_QUEUE_SIZE

logger = logging.getLogger("MiBandDashboard")


class TelemetryHub:
    """Thread-safe ring buffers plus live SSE fan-out."""

    def __init__(self, max_points: int = DEFAULT_MAX_POINTS) -> None:
        self._max_points = max(1, int(max_points))
        self._series: Dict[str, Deque[dict]] = {
            kind: deque(maxlen=self._max_points) for kind in METRIC_KINDS
        }
        self._latest: Dict[str, dict] = {}
        self._counts: Dict[str, int] = {kind: 0 for kind in METRIC_KINDS}
        self._workout: Optional[dict] = None
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._events_sent = 0
        self._state_provider: Optional[Callable[[], Dict[str, Any]]] = None

    @property
    def max_points(self) -> int:
        """Bounded number of samples retained per series."""
        return self._max_points

    # ------------------------------------------------------------- lifecycle
    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the event loop so callbacks from other threads can fan out."""
        self._loop = loop

    def set_state_provider(
        self, provider: Optional[Callable[[], Dict[str, Any]]]
    ) -> None:
        """Attach an optional GUI state snapshot provider for /api/snapshot."""
        self._state_provider = provider

    def publish_event(
        self, kind: str, payload: Dict[str, Any], timestamp: Optional[float] = None
    ) -> None:
        """Fan out an out-of-band control/log event without storing it in metric series."""
        event_ts = time.time() if timestamp is None else float(timestamp)
        record = {
            "kind": kind,
            "ts": round(event_ts, 6),
            "iso_time": utc_iso(event_ts),
            **payload,
        }
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._fanout, record)
                return
            except RuntimeError:
                pass
        self._fanout(record)

    # --------------------------------------------------------------- publish
    def publish_heart_rate(self, bpm: int, timestamp: Optional[float] = None) -> None:
        self._publish("heart_rate", {"bpm": int(bpm)}, timestamp)

    def publish_steps(self, info: dict, timestamp: Optional[float] = None) -> None:
        self._publish(
            "steps",
            {
                "steps": int(info.get("steps", 0)),
                "distance_m": int(info.get("distance_meters", 0)),
                "calories": int(info.get("calories", 0)),
            },
            timestamp,
        )

    def publish_imu(self, info: dict, timestamp: Optional[float] = None) -> None:
        """Publish one dashboard-friendly aggregate per raw IMU packet."""
        samples = info.get("samples") or []
        if not samples:
            return
        magnitudes = [
            math.hypot(
                float(sample.get("ax_g", 0.0)),
                float(sample.get("ay_g", 0.0)),
                float(sample.get("az_g", 0.0)),
            )
            for sample in samples
        ]
        first = samples[0]
        self._publish(
            "imu",
            {
                "sensor_type": int(info.get("type", 0)),
                "sequence": int(info.get("sequence", 0)),
                "samples": len(samples),
                "ax_g": float(first.get("ax_g", 0.0)),
                "ay_g": float(first.get("ay_g", 0.0)),
                "az_g": float(first.get("az_g", 0.0)),
                "magnitude_g": round(sum(magnitudes) / len(magnitudes), 4),
            },
            timestamp,
        )

    def publish_spo2(
        self, spo2: int, status: int = 0, timestamp: Optional[float] = None
    ) -> None:
        self._publish("spo2", {"spo2": int(spo2), "status": int(status)}, timestamp)

    def publish_workout(
        self, workout_snapshot: dict, timestamp: Optional[float] = None
    ) -> None:
        """Broadcast current workout summary/timeline without entering raw series."""
        event_ts = time.time() if timestamp is None else float(timestamp)
        summary = dict(workout_snapshot)
        self._workout = summary
        record = {
            "kind": "workout",
            "ts": round(event_ts, 6),
            "iso_time": utc_iso(event_ts),
            "workout": summary,
        }
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._fanout, record)
                return
            except RuntimeError:
                pass
        self._fanout(record)

    def _publish(self, kind: str, payload: dict, timestamp: Optional[float]) -> None:
        event_ts = time.time() if timestamp is None else float(timestamp)
        record = {"kind": kind, "ts": round(event_ts, 6), "iso_time": utc_iso(event_ts), **payload}
        self._series[kind].append(record)  # deque append is atomic under the GIL
        self._latest[kind] = record
        self._counts[kind] += 1

        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._fanout, record)
                return
            except RuntimeError:  # loop closed during shutdown
                pass
        self._fanout(record)

    def _fanout(self, record: dict) -> None:
        self._events_sent += 1
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(record)
            except asyncio.QueueFull:
                logger.debug("Dropping dashboard event: SSE subscriber is too slow")

    # ------------------------------------------------------------- consumers
    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=SSE_QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def snapshot(self, limit: int = DEFAULT_SNAPSHOT_POINTS) -> dict:
        limit = max(0, int(limit))
        series = {
            kind: list(buffer)[-limit:] if limit else []
            for kind, buffer in self._series.items()
        }
        payload = {
            "type": "snapshot",
            "server_time": round(time.time(), 6),
            "counts": dict(self._counts),
            "latest": dict(self._latest),
            "series": series,
            "subscribers": len(self._subscribers),
            "events_sent": self._events_sent,
        }
        if self._workout is not None:
            payload["workout"] = dict(self._workout)
        if self._state_provider is not None:
            try:
                payload["gui"] = self._state_provider()
            except Exception:
                pass
        return payload

    def history(self, kind: str, limit: int = DEFAULT_SNAPSHOT_POINTS) -> List[dict]:
        if kind not in METRIC_KINDS:
            raise ValueError(f"unknown metric kind: {kind!r}")
        buffer = self._series[kind]
        limit = max(0, int(limit))
        return list(buffer)[-limit:] if limit else []


__all__ = ["TelemetryHub"]
