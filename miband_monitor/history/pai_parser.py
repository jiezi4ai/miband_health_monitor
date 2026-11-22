"""Parser for PAI payloads (fetch type 0x0d).

Layout facts come from Gadgetbridge's ``FetchPaiOperation`` (AGPL-3.0; field
order only, no code copied). Every record is a fixed 102 bytes::

    u8    type            5 = current day, 0 = pre-factory-reset (skipped)
    i32   timestamp       epoch seconds (UTC)
    u8    utc_offset      in quarter hours (+8 h -> 32)
    u8[31] unknown1
    f32   pai_low / pai_moderate / pai_high
    i16   minutes_low / minutes_moderate / minutes_high
    f32   pai_today / pai_total
    u16   counters[3]     values seen: 46, 185, 5 -- meaning unknown
    f32   week[7]         rolling 7-day PAI, newest first
    u8[5] unknown_tail

Captured on a Mi Band 6 (firmware V1.0.6.20) on 2026-11-20 and checked against
the matching Zepp Life page the same morning. All five headline numbers agree
exactly: the app shows ``50 PAI`` (pai_total 50.053), ``今日共获取 14PAI``
(pai_today 14.709), and ``7 / 7 / 0 PAI`` for low/moderate/high
(7.710 / 6.999 / 0.000). ``pai_today`` also equals the sum of its three
components, which is what pinned the offsets.

The band keeps **one snapshot**, not a series, and the app pushes it: with Zepp
Life left alone the record was frozen at 2026-11-10 while the app counted up to
48; after one app sync the record jumped to 2026-11-17 and ``counters[0]`` went
46 -> 47 (exactly one new write). So the band is a mirror of the app's PAI state,
and it lags -- reading it gives "the last state the app handed over", never the
current one.

``week`` is the seven floats at offset 69. ``week[0]`` is bit-identical to
``pai_total`` in **both** captures, and both series decrease monotonically:

* 2026-11-10: 50.053, 46.469, 44.136, 41.007, 34.354, 30.556, 16.527
* 2026-11-17: 65.878, 48.098, 40.726, 33.517, 27.006, 18.208, 6.506

Two readings survive that evidence -- day-by-day 7-day totals (newest first), or
a cumulative/expiry curve inside the current 7-day window. They differ in what
``week[1]`` means (the previous day's total vs the total after one expiry), and
the captures cannot separate them: both windows happened to fall in a ramping
period, where either reading decreases. Tapping the 11-17 and 11-16 bars in the
app (expected 65.9 / 48.1 under the daily reading) would settle it.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone, timedelta
from typing import Optional

from .models import HistoryParseError

#: Every PAI record is this long; the payload must be a whole number of them.
PAI_RECORD_SIZE = 102
#: ``type`` values Gadgetbridge accepts. 0 means data from before a factory
#: reset and is skipped there too.
TYPE_CURRENT = 5
TYPE_LEGACY = 0
_PLAUSIBLE_YEAR_RANGE = (2015, 2100)


def _iso_local(ts: float, offset_quarters: int) -> str:
    """Wall-clock time at the offset the band reported, ISO 8601."""
    tz = timezone(timedelta(minutes=offset_quarters * 15))
    return datetime.fromtimestamp(ts, tz).isoformat(timespec="seconds")


def parse_pai(payload: bytes) -> list[dict]:
    """Decode a 0x0d payload into one dict per record.

    Records of ``type 0`` are dropped: they predate a factory reset and the
    values are not comparable with the current streak.
    """
    if not payload:
        return []
    if len(payload) % PAI_RECORD_SIZE:
        raise HistoryParseError(
            f"PAI payload is {len(payload)} bytes, not a multiple of {PAI_RECORD_SIZE}"
        )

    records: list[dict] = []
    for offset in range(0, len(payload), PAI_RECORD_SIZE):
        block = payload[offset : offset + PAI_RECORD_SIZE]
        kind = block[0]
        if kind not in (TYPE_CURRENT, TYPE_LEGACY):
            raise HistoryParseError(f"unknown PAI record type {kind} at byte {offset}")

        ts = float(struct.unpack_from("<i", block, 1)[0])
        utc_offset = block[5]
        pai_low, pai_moderate, pai_high = struct.unpack_from("<fff", block, 37)
        minutes_low, minutes_moderate, minutes_high = struct.unpack_from("<hhh", block, 49)
        pai_today, pai_total = struct.unpack_from("<ff", block, 55)
        counters = struct.unpack_from("<HHH", block, 63)
        week = [struct.unpack_from("<f", block, 69 + index * 4)[0] for index in range(7)]

        year = datetime.fromtimestamp(ts, timezone.utc).year
        if not _PLAUSIBLE_YEAR_RANGE[0] <= year <= _PLAUSIBLE_YEAR_RANGE[1]:
            raise HistoryParseError(f"implausible PAI timestamp {ts} (year {year})")
        if kind == TYPE_LEGACY:
            continue

        records.append(
            {
                "ts": ts,
                "iso_time": _iso_local(ts, utc_offset),
                "utc_offset_minutes": utc_offset * 15,
                "pai_low": round(pai_low, 3),
                "pai_moderate": round(pai_moderate, 3),
                "pai_high": round(pai_high, 3),
                "minutes_low": int(minutes_low),
                "minutes_moderate": int(minutes_moderate),
                "minutes_high": int(minutes_high),
                "pai_today": round(pai_today, 3),
                "pai_total": round(pai_total, 3),
                "pai_week": [round(value, 3) for value in week],
                "counters": [int(value) for value in counters],
                "unknown1": block[6:37].hex(),
                "unknown_tail": block[97:102].hex(),
            }
        )
    return records


def pai_components_sum(record: dict) -> Optional[float]:
    """``pai_low + pai_moderate + pai_high`` -- the sanity check the capture passed."""
    parts = [record.get(key) for key in ("pai_low", "pai_moderate", "pai_high")]
    if any(part is None for part in parts):
        return None
    return round(sum(parts), 3)
