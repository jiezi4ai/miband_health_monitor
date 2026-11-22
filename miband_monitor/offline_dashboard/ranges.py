"""Semantic time ranges shared by the offline dashboard's charts and KPIs.

``--days N`` stays supported for backward compatibility, but ``--range`` gives
users day/week/month/all buckets that mean the same thing everywhere: the
collection window, the co-axis chart's bucket width and the KPI aggregation
all read from this module.  ``all`` deliberately maps to *no* lower time bound
("full database") rather than a very large number of days.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from miband_monitor.config.defaults import DEFAULT_OFFLINE_DAYS

RANGE_DAY = "day"
RANGE_WEEK = "week"
RANGE_MONTH = "month"
RANGE_ALL = "all"

#: Number of days per semantic range; ``None`` means "no lower bound".
RANGE_DAYS: dict[str, Optional[int]] = {
    RANGE_DAY: 1,
    RANGE_WEEK: 7,
    RANGE_MONTH: 30,
    RANGE_ALL: None,
}
RANGE_CHOICES = tuple(RANGE_DAYS)
#: Display copy for the header and KPI hints.
RANGE_LABELS = {
    RANGE_DAY: "昨晚",
    RANGE_WEEK: "近 7 天",
    RANGE_MONTH: "近 30 天",
    RANGE_ALL: "全库",
}


def normalize_range(value: Optional[str]) -> Optional[str]:
    """Validate a range name, preserving ``None`` (legacy ``--days`` mode)."""
    if value is None or value == "":
        return None
    if value not in RANGE_DAYS:
        raise ValueError(f"unknown range {value!r}; choose from {', '.join(RANGE_CHOICES)}")
    return value


def resolve_ranges(
    range_name: Optional[str] = None,
    kpi_range: Optional[str] = None,
    days: int = DEFAULT_OFFLINE_DAYS,
    *,
    now: Optional[datetime] = None,
) -> tuple[Optional[str], str, float, Optional[int]]:
    """Resolve ``(range, kpi_range, since, window_days)`` for one collection.

    The chart window follows ``--range``; the KPI card range follows
    ``--kpi-range`` and defaults to the chart range.  When only ``--days`` is
    given the historical numeric-window behaviour is preserved and the KPIs
    keep their original "last night" semantics.
    """
    selected = normalize_range(range_name)
    kpi = normalize_range(kpi_range) or selected or RANGE_DAY
    if selected is None and kpi_range is None:
        window_days: Optional[int] = int(days)
    else:
        # A wider KPI range must see the data it aggregates: the effective
        # window is the broader of the two selections.
        candidates = [
            RANGE_DAYS[name]
            for name in (selected, kpi)
            if name is not None and RANGE_DAYS[name] is not None
        ]
        if any(RANGE_DAYS[name] is None for name in (selected, kpi) if name is not None):
            window_days = None
        else:
            window_days = max(candidates) if candidates else int(days)
    moment = now or datetime.now()
    if window_days is None:
        since = 0.0
    else:
        since = (moment - timedelta(days=window_days)).replace(
            second=0, microsecond=0
        ).timestamp()
    return selected, kpi, since, window_days
