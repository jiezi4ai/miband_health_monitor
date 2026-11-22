"""Gather everything the offline dashboard renders into one payload.

The payload is the whole contract between Python and the bundled JavaScript:
metadata, sleep sessions (with pre-rendered hypnograms), heart rate, activity
bands, the co-axis bucket series, steps, point SpO2 and the night-long sleep
SpO2 series, plus the KPI cards.  It is a pure function of the SQLite contents
and the selected time range, so it can be checked without a browser.
"""

from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from miband_monitor.config.defaults import DEFAULT_OFFLINE_DAYS
from miband_monitor.sleep import BAND_NONWEAR, activity_band, analyze

from .combined import bucket_seconds, package_combined
from .constants import CLOCK_FORMAT, DATE_FORMAT, GENERATED_AT_FORMAT, LOCAL_DATETIME_FORMAT
from .kpis import _kpis
from .packaging import _package_activity, _package_heart_rate, _package_steps
from .ranges import RANGE_LABELS, resolve_ranges
from .sources import (
    _load_activity,
    _load_activity_summaries,
    _load_heart_rate,
    _load_spo2,
    _load_spo2_sleep,
    _local,
)
from .svg import flat_in_bed_svg, hypnogram_svg


def collect(
    db_path: str | Path,
    *,
    days: int = DEFAULT_OFFLINE_DAYS,
    spo2_sleep_path: str | Path | None = None,
    range: Optional[str] = None,
    kpi_range: Optional[str] = None,
) -> dict[str, Any]:
    """Gather everything the dashboard needs into one JSON-serialisable dict.

    ``range`` selects the semantic window (day/week/month/all); ``kpi_range``
    selects the card aggregation independently and defaults to ``range``.
    Leaving both unset preserves the historical numeric ``days`` window.
    """
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {path}")

    selected, kpi, since, window_days = resolve_ranges(range, kpi_range, days)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        activity = _load_activity(conn, since)
        hr_rows = _load_heart_rate(conn, since)
        spo2_rows = _load_spo2(conn, since)
        spo2_sleep_rows, spo2_sleep_source = _load_spo2_sleep(
            conn, since, db_path, spo2_sleep_path
        )
        summaries = _load_activity_summaries(conn, since)
    finally:
        conn.close()

    spo2_sleep_values = [row["spo2"] for row in spo2_sleep_rows]

    sleep_result = analyze(activity)
    sessions = []
    for session in sleep_result["_sessions"]:
        payload = session.as_dict()
        # Off-wrist minutes are *measured* (0xF3); a minute with no record is
        # not.  Give the SVG the per-minute flags so it can hatch one and leave
        # the other transparent instead of painting a fake night of sleep.
        nonwear = [activity_band(sample) == BAND_NONWEAR for sample in session.samples]
        sessions.append({
            **payload,
            "hypnogram": session.hypnogram(),
            "stages": list(session.stages),
            "nonwear": nonwear,
            # Without heart rate there is nothing to stack: show the in-bed span
            # as one flat band instead of four empty lanes.
            "svg": hypnogram_svg(session.stages, nonwear=nonwear, show_unknown=True)
            if payload["heart_rate_available"]
            else flat_in_bed_svg(session.minutes),
            "clock": _local(session.start, CLOCK_FORMAT),
            # Labelled by the date the night started, the way Zepp Life does.
            "date": _local(session.start, DATE_FORMAT),
            # A session starting at the very first sample is the tail of a
            # night whose beginning the band already overwrote. Say so.
            "truncated_start": bool(activity)
            and abs(session.start - activity[0]["ts"]) <= 60,
        })

    activity_pkg = _package_activity(
        activity,
        {sample["ts"] for session in sleep_result["_sessions"] for sample in session.samples},
    )
    range_label = RANGE_LABELS.get(selected) or (
        "全库" if window_days is None else f"近 {window_days} 天"
    )
    return {
        "meta": {
            "generated_at": datetime.now().strftime(GENERATED_AT_FORMAT),
            "source": str(db_path),
            "days": window_days,
            "range_name": selected or "custom",
            "kpi_range": kpi,
            "kpi_label": RANGE_LABELS[kpi],
            "range_label": range_label,
            "activity_samples": len(activity),
            "hr_samples": len(hr_rows),
            "spo2_samples": len(spo2_rows),
            "spo2_sleep_samples": len(spo2_sleep_rows),
            "summary_count": len(summaries),
            "spo2_sleep_source": spo2_sleep_source,
            "range": [_local(activity[0]["ts"]) if activity else None,
                      _local(activity[-1]["ts"]) if activity else None],
        },
        "sleep": {
            "sessions": sessions,
            "totals": sleep_result["totals"],
            "not_worn": sleep_result["not_worn"],
        },
        "hr": _package_heart_rate(hr_rows, activity),
        "activity": activity_pkg,
        "combined": package_combined(
            activity, hr_rows, activity_pkg["points"],
            bucket_seconds(selected, window_days),
        ),
        "steps": _package_steps(activity),
        "sports": [
            {
                **row,
                "start": _local(row["ts"], LOCAL_DATETIME_FORMAT),
                "end": _local(row["end_ts"], CLOCK_FORMAT),
            }
            for row in summaries
        ],
        "spo2": [
            {**item, "time": _local(item["ts"], LOCAL_DATETIME_FORMAT)} for item in spo2_rows
        ],
        "spo2_sleep": {
            "points": [[row["ts"], row["spo2"]] for row in spo2_sleep_rows],
            "count": len(spo2_sleep_rows),
            "min": min(spo2_sleep_values) if spo2_sleep_values else None,
            "max": max(spo2_sleep_values) if spo2_sleep_values else None,
            "avg": (
                round(statistics.mean(spo2_sleep_values), 1)
                if spo2_sleep_values else None
            ),
            "source": spo2_sleep_source,
        },
        "kpi": _kpis(
            sessions, activity, spo2_rows, hr_rows,
            sleep_result["not_worn"], spo2_sleep_rows, range=kpi,
        ),
    }
