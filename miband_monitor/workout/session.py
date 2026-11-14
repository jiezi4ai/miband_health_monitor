"""Stateful workout session aggregator and live/gap-fill timeline fusion."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Optional

from .constants import (
    DEFAULT_HR_SMOOTHING_WINDOW,
    DEFAULT_WORKOUT_GAP_FILL_MIN_SECONDS,
    STATE_FINISHED,
    STATE_GAP_FILLING,
    STATE_RECONNECTING,
    STATE_STREAMING,
    WORKOUT_HR_ZONES,
)
from .metrics import (
    CumulativeCounter,
    WorkoutProfile,
    classify_hr_zone,
    estimate_kcal_per_min,
    is_valid_bpm,
)
from .snapshot import format_workout_snapshot

_MAX_DT_SECONDS = 60.0
_MAX_TIMELINE_POINTS = 3600


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds")


class WorkoutSession:
    """Thread-safe tracker for real-time and gap-filled workout metrics."""

    def __init__(
        self,
        profile: Optional[WorkoutProfile] = None,
        *,
        started_at: Optional[float] = None,
        gap_fill_min_seconds: float = DEFAULT_WORKOUT_GAP_FILL_MIN_SECONDS,
        smoothing_window: int = DEFAULT_HR_SMOOTHING_WINDOW,
    ) -> None:
        self.profile = profile or WorkoutProfile()
        self.started_at = float(time.time() if started_at is None else started_at)
        self.ended_at: Optional[float] = None
        self.gap_fill_min_seconds = max(0.0, float(gap_fill_min_seconds))

        self._lock = threading.Lock()
        self._state = STATE_STREAMING
        self._reconnect_count = 0
        self._battery_pct: Optional[int] = None
        self._battery_updated_at: Optional[float] = None

        self._steps_counter = CumulativeCounter()
        self._distance_counter = CumulativeCounter()
        self._band_kcal_counter = CumulativeCounter()

        self._smoothing_buf: Deque[int] = deque(maxlen=max(1, int(smoothing_window)))
        self._valid_hr_count = 0
        self._filtered_hr_count = 0
        self._hr_sum = 0
        self._latest_hr: Optional[int] = None
        self._min_hr: Optional[int] = None
        self._max_hr: Optional[int] = None
        self._last_valid_hr_ts: Optional[float] = None
        self._last_valid_hr_bpm: Optional[int] = None
        self._zone_seconds: dict[int, float] = {0: 0.0, **{z[0]: 0.0 for z in WORKOUT_HR_ZONES}}
        self._estimated_hr_kcal = 0.0

        self._live_points: Deque[dict] = deque(maxlen=_MAX_TIMELINE_POINTS)
        self._gap_fill_points: dict[int, dict] = {}

        self._active_gap_start: Optional[float] = None
        self._gaps: list[dict] = []

    def record_heart_rate(self, bpm: int, ts: Optional[float] = None) -> dict:
        """Ingest one live heart-rate sample (BPM) and update zones/kcal."""
        now_ts = float(time.time() if ts is None else ts)
        val = int(bpm)
        with self._lock:
            if not is_valid_bpm(val):
                self._filtered_hr_count += 1
                return {"accepted": False, "bpm": val, "ts": now_ts}

            if self._last_valid_hr_ts is not None and self._last_valid_hr_bpm is not None:
                dt = max(0.0, min(_MAX_DT_SECONDS, now_ts - self._last_valid_hr_ts))
                if dt > 0:
                    prev_zone = classify_hr_zone(self._last_valid_hr_bpm, self.profile.resolved_hr_max)
                    if prev_zone is not None:
                        self._zone_seconds[prev_zone[0]] = (
                            self._zone_seconds.get(prev_zone[0], 0.0) + dt
                        )
                    rate = estimate_kcal_per_min(self._last_valid_hr_bpm, self.profile)
                    self._estimated_hr_kcal += rate * (dt / 60.0)

            self._last_valid_hr_ts = now_ts
            self._last_valid_hr_bpm = val
            self._latest_hr = val
            self._valid_hr_count += 1
            self._hr_sum += val
            self._min_hr = val if self._min_hr is None else min(self._min_hr, val)
            self._max_hr = val if self._max_hr is None else max(self._max_hr, val)
            self._smoothing_buf.append(val)

            smoothed = round(sum(self._smoothing_buf) / len(self._smoothing_buf), 1)
            zone = classify_hr_zone(val, self.profile.resolved_hr_max)
            self._live_points.append(
                {
                    "ts": now_ts,
                    "iso_time": _iso_utc(now_ts),
                    "bpm": val,
                    "smoothed_bpm": smoothed,
                    "zone": zone[0] if zone else None,
                    "source": "live",
                }
            )
            return {
                "accepted": True,
                "bpm": val,
                "smoothed_bpm": smoothed,
                "zone": zone,
                "ts": now_ts,
            }

    def record_steps(self, info: dict, ts: Optional[float] = None) -> dict:
        """Ingest one 0x0007 cumulative steps/distance/calories notification."""
        now_ts = float(time.time() if ts is None else ts)
        with self._lock:
            steps = self._steps_counter.update(int(info.get("steps", 0)))
            dist = self._distance_counter.update(int(info.get("distance_meters", 0)))
            kcal = self._band_kcal_counter.update(int(info.get("calories", 0)))
            return {
                "ts": now_ts,
                "net_steps": steps,
                "net_distance_m": dist,
                "net_band_kcal": kcal,
            }

    def record_battery(self, level: Optional[int], ts: Optional[float] = None) -> None:
        """Record an optional battery level reading (0..100%)."""
        if level is None:
            return
        now_ts = float(time.time() if ts is None else ts)
        with self._lock:
            self._battery_pct = max(0, min(100, int(level)))
            self._battery_updated_at = now_ts

    def on_disconnect(self, ts: Optional[float] = None) -> None:
        """Mark link loss and reset inter-sample live HR dt integration."""
        now_ts = float(time.time() if ts is None else ts)
        with self._lock:
            self._state = STATE_RECONNECTING
            self._last_valid_hr_ts = None
            self._last_valid_hr_bpm = None
            if self._active_gap_start is None:
                self._active_gap_start = now_ts

    def on_reconnect(self, ts: Optional[float] = None) -> Optional[dict]:
        """Close the active disconnect window and report if gap-fill is warranted."""
        now_ts = float(time.time() if ts is None else ts)
        with self._lock:
            self._reconnect_count += 1
            if self._active_gap_start is None:
                self._state = STATE_STREAMING
                return None
            gap_start = self._active_gap_start
            self._active_gap_start = None
            duration = max(0.0, now_ts - gap_start)
            needs_gap_fill = duration >= self.gap_fill_min_seconds
            gap_entry = {
                "start_ts": gap_start,
                "end_ts": now_ts,
                "duration_s": round(duration, 2),
                "gap_filled_samples": 0,
                "status": "pending" if needs_gap_fill else "short_skip",
            }
            self._gaps.append(gap_entry)
            self._state = STATE_GAP_FILLING if needs_gap_fill else STATE_STREAMING
            return dict(gap_entry)

    def mark_state(self, state: str) -> None:
        """Explicitly set current workout state."""
        with self._lock:
            self._state = state

    def ingest_gap_fill(
        self,
        samples: list[dict],
        *,
        gap_start: Optional[float] = None,
        gap_end: Optional[float] = None,
        status: str = "filled",
    ) -> int:
        """Merge band-side ACTIVITY (0x01) minute samples into timeline memory."""
        added = 0
        with self._lock:
            for sample in samples:
                ts_val = sample.get("ts")
                if ts_val is None:
                    continue
                bpm = int(sample.get("heart_rate", 0))
                if not is_valid_bpm(bpm):
                    continue
                key = int(round(float(ts_val)))
                if key not in self._gap_fill_points:
                    added += 1
                self._gap_fill_points[key] = {
                    "ts": float(ts_val),
                    "iso_time": _iso_utc(float(ts_val)),
                    "bpm": bpm,
                    "steps": int(sample.get("steps", 0)),
                    "intensity": int(sample.get("intensity", 0)),
                    "kind": int(sample.get("kind", 0)),
                    "source": "gap_fill",
                }
            if self._gaps:
                target = self._gaps[-1]
                if gap_start is not None:
                    for gap in reversed(self._gaps):
                        if abs(gap["start_ts"] - gap_start) < 1e-3:
                            target = gap
                            break
                target["gap_filled_samples"] += added
                target["status"] = status
            if self._state == STATE_GAP_FILLING:
                self._state = STATE_STREAMING
        return added

    def finish(self, ts: Optional[float] = None) -> dict:
        """Finalize workout timing and return the final summary."""
        now_ts = float(time.time() if ts is None else ts)
        with self._lock:
            self.ended_at = max(self.started_at, now_ts)
            self._state = STATE_FINISHED
            return self._build_snapshot_locked(include_timeline=False)

    def snapshot(self, timeline_limit: int = 600) -> dict:
        """Return a JSON-serializable snapshot for UI & SSE updates."""
        with self._lock:
            return self._build_snapshot_locked(
                include_timeline=True,
                timeline_limit=timeline_limit,
            )

    def summary(self) -> dict:
        """Return the full workout summary (without truncating gap list)."""
        with self._lock:
            return self._build_snapshot_locked(include_timeline=False)

    def fused_timeline(self, limit: int = 600) -> list[dict]:
        """Return merged chronological HR timeline of live + gap-fill points."""
        with self._lock:
            return self._fused_timeline_locked(limit)

    # -------------------------------------------------------------- internals
    def _fused_timeline_locked(self, limit: int) -> list[dict]:
        merged = list(self._live_points) + list(self._gap_fill_points.values())
        merged.sort(key=lambda item: float(item["ts"]))
        if limit > 0 and len(merged) > limit:
            return merged[-limit:]
        return merged

    def _build_snapshot_locked(
        self,
        *,
        include_timeline: bool,
        timeline_limit: int = 600,
    ) -> dict:
        return format_workout_snapshot(
            state=self._state,
            started_at=self.started_at,
            ended_at=self.ended_at,
            profile=self.profile,
            smoothing_values=list(self._smoothing_buf),
            valid_hr_count=self._valid_hr_count,
            filtered_hr_count=self._filtered_hr_count,
            hr_sum=self._hr_sum,
            latest_hr=self._latest_hr,
            min_hr=self._min_hr,
            max_hr=self._max_hr,
            zone_seconds=self._zone_seconds,
            estimated_hr_kcal=self._estimated_hr_kcal,
            net_steps=self._steps_counter.total,
            net_distance_m=self._distance_counter.total,
            net_band_kcal=self._band_kcal_counter.total,
            battery_pct=self._battery_pct,
            battery_updated_at=self._battery_updated_at,
            reconnect_count=self._reconnect_count,
            gaps=self._gaps,
            gap_filled_count=len(self._gap_fill_points),
            timeline=self._fused_timeline_locked(timeline_limit) if include_timeline else None,
        )
