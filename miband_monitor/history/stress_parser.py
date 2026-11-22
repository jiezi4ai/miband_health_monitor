"""Parser for automatic stress payloads (fetch type 0x13).

One byte per minute, anchored at the start timestamp the band echoes in the
start-date reply. Layout facts follow Gadgetbridge's ``FetchStressAutoOperation``
(AGPL-3.0; field order only, no code copied), extended by one sentinel that
Gadgetbridge does not handle:

* ``0xFF`` -- no reading (band not worn / not measuring);
* ``0xFE`` -- also not a value. Gadgetbridge would publish it as stress 254;
  in a real 5761-byte capture **every** byte with the high bit set was exactly
  ``0xFE``, and nothing between 101 and 253 ever appeared, so it is a marker, not
  a reading. Both are skipped here;
* ``1..100`` -- the stress score, in Zepp's own bands (0-39 relaxed, 40-59 mild,
  60-79 moderate, 80-100 high).

The capture (2026-11-13 10:58 -> 2026-11-17 10:58) yielded 600 valid minutes with
mean 23-31 per day and 67-86 % of readings in the relaxed band, which matches the
shape of the app's "今日压力" page (average 20, 88 % relaxed). The exact scale is
still waiting on a per-day Zepp number -- see
docs/validation/derived-metrics-probe-2026-11.zh-CN.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import HistoryParseError

#: No reading at all (band not worn / measurement off).
NO_READING = 0xFF
#: Marker byte: high bit set, but not a score. Gadgetbridge reads it as 254.
UNMEASURED = 0xFE
#: Highest value the firmware emits as a real score.
MAX_STRESS = 100

#: Zepp's bands, for callers that want the same four buckets the app shows.
BANDS = ((0, 39, "relaxed"), (40, 59, "mild"), (60, 79, "moderate"), (80, 100, "high"))


def band_of(stress: int) -> str:
    """Zepp's bucket name for one score."""
    for low, high, name in BANDS:
        if low <= stress <= high:
            return name
    raise ValueError(f"stress out of range: {stress}")


def parse_stress_auto(payload: bytes, start_timestamp: float) -> list[dict]:
    """Decode a 0x13 payload into per-minute stress samples.

    Minutes carrying a sentinel are omitted rather than published as 0: "no
    measurement" and "zero stress" are different facts, and averaging them
    together would drag every daily average toward zero.
    """
    samples: list[dict] = []
    for index, value in enumerate(payload):
        if value in (NO_READING, UNMEASURED):
            continue
        if value > MAX_STRESS:
            raise HistoryParseError(
                f"stress value {value} at minute {index} exceeds {MAX_STRESS}; "
                "the payload layout has changed"
            )
        ts = start_timestamp + index * 60
        samples.append(
            {
                "ts": float(ts),
                "iso_time": datetime.fromtimestamp(ts).isoformat(timespec="seconds"),
                "stress": int(value),
                "band": band_of(value),
            }
        )
    return samples


def coverage(payload: bytes) -> Optional[float]:
    """Share of minutes that actually carry a score (0..1), or None when empty."""
    if not payload:
        return None
    measured = sum(1 for value in payload if value not in (NO_READING, UNMEASURED))
    return round(measured / len(payload), 4)
