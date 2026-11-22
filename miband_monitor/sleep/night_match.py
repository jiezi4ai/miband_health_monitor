"""Match a Zepp Life night to the band session that produced it.

Night identity is the evening the sleep started on, which is also how the band's
own sessions are keyed: ``2026-11-13`` means the sleep that began on the evening
of the 13th and ended on the morning of the 14th.

Zepp Life dates that same page **one day later**: its header is the morning you
woke up. Confirmed against hardware on 2026-11-20 -- the newest entry is headed
"11月20日 / 昨晚睡眠" although it starts at 22:28 on the 19th, and the seven
November pages line up with our sessions only when shifted by a day (four of the
seven end within one minute of the band's own session end). So subtract one day
from the page header when writing the JSON.

Keeping this out of :mod:`calibration` matters because a wrong match is silent:
it reports a plausible table for the wrong sessions.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional


def local_date(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def find_session(
    result: dict, date: str, window: Optional[list[str]] = None
) -> Optional[Any]:
    """The band session that corresponds to the night of *date*.

    One date can hold several sessions -- naps are separate sessions, and the
    first one of the day is usually not the night. Returning it silently compared
    a 40-minute nap against a 480-minute reference and made every model look
    wrong. When the app's window is known the night is the session with the most
    minutes inside it; without a window the longest session wins.
    """
    candidates = [s for s in result["_sessions"] if local_date(s.start) == date]
    if not candidates:
        return None
    bounds = window_bounds({"date": date, "window": window}) if window else None
    if bounds is not None:
        low, high = bounds
        scored = [
            (sum(1 for m in s.samples if low <= m["ts"] <= high), s)
            for s in candidates
        ]
        overlap, best = max(scored, key=lambda item: (item[0], item[1].end - item[1].start))
        return best if overlap else None
    return max(candidates, key=lambda s: s.end - s.start)


def nonwear_minutes(result: dict, date: str) -> int:
    """Minutes of ``0xF3`` the band recorded on the evening of *date*."""
    return sum(
        span["minutes"]
        for span in result.get("not_worn", [])
        if span.get("start", "").startswith(date)
    )


def window_bounds(night: dict) -> Optional[tuple[float, float]]:
    """Zepp's in-bed window as epoch seconds.

    ``["22:44", "05:11"]`` is one night that crosses midnight: an end that is not
    after the start rolls over to the next day. ``night["date"]`` is the evening
    the sleep started on (see the module docstring -- the app's own page header
    is one day later).
    """
    window = night.get("window")
    if not window:
        return None
    start = datetime.strptime(f"{night['date']} {window[0]}", "%Y-%m-%d %H:%M")
    end = datetime.strptime(f"{night['date']} {window[1]}", "%Y-%m-%d %H:%M")
    if end <= start:
        end += timedelta(days=1)
    return start.timestamp(), end.timestamp()


def overlap_minutes(night: dict, session: Any) -> Optional[int]:
    """How many of the session's minutes fall inside the window Zepp reports."""
    bounds = window_bounds(night)
    if bounds is None:
        return None
    low, high = bounds
    return sum(1 for sample in session.samples if low <= sample["ts"] <= high)
