"""Parser for SPORTS_SUMMARIES (0x05) payloads.

Each 0x05 fetch returns **one** workout summary.  The binary layout follows
Gadgetbridge's ``HuamiActivitySummaryParser`` (AGPL-3.0; layout facts only, no
code copied): a version word discriminates the field order, and Band 6 emits
the ``version >= 512`` family -- a captured Mi Band 6 v519 payload pinned in the
tests decodes to the same steps/calories/HR values Gadgetbridge reports for it.

Only summary fields that the band actually measured are exposed.  Values the
firmware uses as sentinels are dropped rather than published as data:
``min_hr == -256`` (v519 garbage), ``min_pace > 60 s/m`` (paused workout), and
the ``-100000/100000`` altitude markers.  Band 6 has no GPS hardware, so
``has_gps`` is expected to be false and no track is fetched.
"""

from __future__ import annotations

import struct
from typing import Any, Optional

from .models import HistoryParseError

#: Summary payload revisions seen on Huami devices; >= 512 shares one layout.
MIN_SUPPORTED_VERSION = 512
SENTINEL_MIN_ALTITUDE = -100000.0
SENTINEL_MAX_ALTITUDE = 100000.0
#: v519 garbage sentinel for min HR (observed as -256 on a Mi Band 6).
SENTINEL_MIN_HR = -256
#: Firmware uses > 60 s/m as "paused" for the slowest pace.
MAX_PLAUSIBLE_PACE_S_PER_M = 60.0

#: HuamiSportsActivityType code -> label (protocol facts from Gadgetbridge).
ACTIVITY_KINDS = {
    1: "outdoor_running", 2: "treadmill", 3: "walking", 4: "cycling",
    5: "exercise", 6: "swimming", 7: "open_water_swimming", 8: "indoor_cycling",
    9: "elliptical_trainer", 10: "climbing", 15: "outdoor_hiking",
    0x12: "soccer", 0x15: "jump_rope", 0x17: "rowing_machine",
    0x34: "strength_training", 0x3C: "yoga", 0x4E: "cricket",
    0x55: "basketball", 0x59: "ping_pong", 0x5C: "badminton",
}


class _Cursor:
    """Little-endian reader that turns a short payload into a parse error."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.offset = 0

    def _take(self, fmt: str, size: int) -> tuple:
        if self.offset + size > len(self.payload):
            raise HistoryParseError(
                f"summary payload truncated at offset {self.offset} "
                f"(need {size} more bytes, have {len(self.payload) - self.offset})"
            )
        values = struct.unpack_from(fmt, self.payload, self.offset)
        self.offset += size
        return values

    def u16(self) -> int:
        return self._take("<H", 2)[0]

    def i16(self) -> int:
        return self._take("<h", 2)[0]

    def i32(self) -> int:
        return self._take("<i", 4)[0]

    def u32(self) -> int:
        return self._take("<I", 4)[0]

    def f32(self) -> float:
        return self._take("<f", 4)[0]

    def skip(self, count: int) -> None:
        if self.offset + count > len(self.payload):
            raise HistoryParseError("summary payload truncated while skipping padding")
        self.offset += count


def _optional_hr(value: int) -> Optional[int]:
    return value if value > 0 else None


def _optional_altitude(value: float, sentinel: float) -> Optional[float]:
    return None if value == sentinel else round(value, 2)


def _optional_pace(value: float) -> Optional[float]:
    if value <= 0 or value > MAX_PLAUSIBLE_PACE_S_PER_M:
        return None
    return round(value, 3)


def parse_sports_summary(payload: bytes) -> dict[str, Any]:
    """Decode one 0x05 workout summary into a flat, storable dict."""
    if len(payload) < 12:
        raise HistoryParseError(f"summary payload too short: {len(payload)} bytes")
    cur = _Cursor(payload)
    version = cur.u16()
    if version < MIN_SUPPORTED_VERSION:
        raise HistoryParseError(
            f"unsupported summary version {version}; Band 6 reports >= {MIN_SUPPORTED_VERSION}"
        )
    raw_kind = cur.u16()
    start_ts = cur.u32()
    end_ts = cur.u32()
    base_lon, base_lat, base_alt = cur.i32(), cur.i32(), cur.i32()

    min_hr: Optional[int] = None
    if version == 519:
        cur.skip(1)
        min_hr = _optional_hr(cur.i16())
        if cur.offset < 0x8C:
            cur.skip(0x8C - cur.offset)
    elif version == 516:
        cur.skip(4)

    steps = cur.i32()
    active_seconds = cur.i32()
    cur.skip(16)  # max/min latitude/longitude (no GPS on Band 6)
    calories = cur.f32()
    distance_m = cur.f32()
    _ascent, _descent = cur.f32(), cur.f32()
    max_alt, min_alt = cur.f32(), cur.f32()
    average_alt = cur.f32()
    max_speed, min_speed, average_speed = cur.f32(), cur.f32(), cur.f32()
    min_pace, max_pace, _average_pace = cur.f32(), cur.f32(), cur.f32()
    max_cadence, min_cadence, average_cadence = cur.f32(), cur.f32(), cur.f32()
    max_stride, min_stride, _average_stride = cur.f32(), cur.f32(), cur.f32()
    _distance_from_track = cur.f32()
    cur.skip(4)  # unknown
    average_hr = _optional_hr(cur.i16())
    average_km_pace = cur.i16()
    _average_stride_cm = cur.i16()
    max_hr = _optional_hr(cur.i16())

    duration = max(0, end_ts - start_ts)
    return {
        "ts": float(start_ts),
        "end_ts": float(end_ts),
        "duration_s": duration,
        "version": version,
        "kind_code": raw_kind,
        "kind_name": ACTIVITY_KINDS.get(raw_kind, f"unknown_{raw_kind}"),
        "steps": max(0, steps),
        "active_seconds": max(0, active_seconds),
        "calories": round(calories, 1),
        "distance_m": round(distance_m, 1),
        "average_hr": average_hr,
        "max_hr": max_hr,
        "min_hr": min_hr,
        "average_pace_s_per_km": average_km_pace or None,
        "min_pace_s_per_m": _optional_pace(min_pace),
        "max_pace_s_per_m": _optional_pace(max_pace),
        "speed_max_mps": round(max_speed, 3),
        "speed_min_mps": round(min_speed, 3),
        "speed_avg_mps": round(average_speed, 3),
        "cadence_max_spm": round(max_cadence * 60) if max_cadence else None,
        "cadence_min_spm": round(min_cadence * 60) if min_cadence else None,
        "cadence_avg_spm": round(average_cadence * 60) if average_cadence else None,
        "stride_max_cm": round(max_stride * 100) if max_stride else None,
        "stride_min_cm": round(min_stride * 100) if min_stride else None,
        "altitude_max_m": _optional_altitude(max_alt, SENTINEL_MIN_ALTITUDE),
        "altitude_min_m": _optional_altitude(min_alt, SENTINEL_MAX_ALTITUDE),
        "altitude_avg_m": round(average_alt, 2) if average_alt else None,
        "base_longitude": base_lon,
        "base_latitude": base_lat,
        "base_altitude": base_alt,
        "has_gps": bool(base_lon or base_lat),
        "source": "band_summary",
    }


__all__ = ["ACTIVITY_KINDS", "parse_sports_summary"]
