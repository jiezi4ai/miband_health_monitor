"""Bucket packaging for the co-axis (activity + heart rate + sleep band) chart.

Buckets are aligned to *local* clock boundaries so a day row is a calendar day,
not a UTC one.  A bucket with no band-side minute keeps ``steps = null``: the
renderer must leave a gap, never invent a zero bar.  Heart rate and the sleep
band are independent channels on the same time axis for the same reason.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from .packaging import _valid_hr


def bucket_seconds(range_name: Optional[str], window_days: Optional[int]) -> int:
    """Width of one co-axis bucket in seconds for the selected granularity."""
    if range_name == "day" or (range_name is None and window_days == 1):
        return 600  # 10-minute buckets keep a single night readable
    if window_days is not None and window_days <= 7:
        return 3600  # hourly buckets for a week
    return 86400  # calendar-day buckets for a month / the full archive


def bucket_start(ts: float, seconds: int) -> float:
    """Floor *ts* to a local clock boundary (minute hour, or midnight)."""
    moment = datetime.fromtimestamp(ts)
    if seconds >= 86400:
        floored = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    elif seconds >= 3600:
        floored = moment.replace(minute=0, second=0, microsecond=0)
    else:
        step = max(1, seconds // 60)
        floored = moment.replace(minute=moment.minute // step * step, second=0, microsecond=0)
    return floored.timestamp()


def package_combined(
    activity: Sequence[dict],
    hr_rows: Sequence[tuple[float, int]],
    activity_points: Sequence[Sequence[float]],
    seconds: int,
) -> dict[str, Any]:
    """Return ``[bucket_ts, steps|None, bpm|None, band|None]`` rows.

    ``activity_points`` comes from :func:`_package_activity`, so the band code
    still has a single source (``sleep/samples.py``).  ``max`` picks the most
    salient band because the canonical codes are ordered rest < active <
    sleep < nonwear -- a bucket containing one off-wrist minute is not painted
    as sleep.
    """
    codes = {float(ts): int(code) for ts, code in activity_points}
    slots: dict[float, dict[str, Any]] = {}

    def slot(ts: float) -> dict[str, Any]:
        return slots.setdefault(
            bucket_start(ts, seconds),
            {"steps": 0, "bands": [], "hrs": [], "has_activity": False},
        )

    for item in activity:
        entry = slot(item["ts"])
        entry["has_activity"] = True
        entry["steps"] += int(item["steps"])
        entry["bands"].append(codes.get(float(item["ts"])))
        bpm = _valid_hr(int(item["heart_rate"]))
        if bpm is not None:
            entry["hrs"].append(bpm)
    for ts, bpm in hr_rows:
        measured = _valid_hr(bpm)
        if measured is not None:
            slot(ts)["hrs"].append(measured)

    points = []
    for ts in sorted(slots):
        entry = slots[ts]
        bands = [code for code in entry["bands"] if code is not None]
        hrs = entry["hrs"]
        points.append([
            ts,
            entry["steps"] if entry["has_activity"] else None,
            round(sum(hrs) / len(hrs), 1) if hrs else None,
            max(bands) if bands else None,
        ])
    return {"points": points, "bucket_seconds": seconds}
