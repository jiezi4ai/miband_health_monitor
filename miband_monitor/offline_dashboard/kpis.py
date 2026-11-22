"""Dashboard KPI cards: labels, values and the hints explaining them.

The ordering and text of the cards is part of the report's contract.  The
default ``range="day"`` keeps the historical semantics byte-for-byte: the most
recent night is only reported as sleep when it has heart rate, the longest
off-wrist stretch is called out separately, and the SpO2 minimum is taken
across both the point-measurement and night-long series.  Wider ranges average
the sleep cards over the nights in the window; every card still carries the
range in its hint so a number is never read out of context.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Sequence

from miband_monitor.sleep import STAGE_DEEP

from .constants import DAY_FORMAT
from .packaging import _valid_hr
from .ranges import RANGE_DAY, RANGE_LABELS
from .strings import (
    UNIT_BPM,
    UNIT_HOURS,
    UNIT_PERCENT,
    UNIT_STEPS,
    VALUE_PLACEHOLDER,
    HINT_NO_DATA,
    HINT_NO_HR_DATA,
    HINT_NO_HR_SLEEP_UNKNOWN,
    HINT_NO_SPO2_RECORDS,
    LABEL_BAND_NOT_WORN,
    LABEL_DEEP_SHARE,
    LABEL_DEEP_SHARE_AVG,
    LABEL_HEART_RATE_RANGE,
    LABEL_LAST_NIGHT_IN_BED,
    LABEL_LAST_NIGHT_SLEEP,
    LABEL_SLEEP_AVG,
    LABEL_SLEEP_EFFICIENCY,
    LABEL_SLEEP_EFFICIENCY_AVG,
    LABEL_SPO2_MIN,
    LABEL_STEPS_AVG,
    LABEL_STEPS_TODAY,
    hint_awakenings,
    hint_days,
    hint_fell_asleep,
    hint_hr_mean,
    hint_minutes,
    hint_most_recent,
    hint_nights,
    hint_since,
    hint_spo2_split,
    hint_steps_activity,
)


def _last_night_cards(sessions: Sequence[dict]) -> list[dict[str, str]]:
    """The original KPI semantics: only the most recent night counts."""
    kpis: list[dict[str, str]] = []
    # The most recent night can be one the band spent on a table. Reporting it as
    # "in bed" invents eight hours that never happened.
    if sessions:
        last = sessions[-1]
        if last["heart_rate_available"]:
            kpis.append({"label": LABEL_LAST_NIGHT_SLEEP, "value": f"{last['minutes_asleep'] / 60:.1f}",
                         "unit": UNIT_HOURS,
                         "hint": hint_fell_asleep(last["start"][5:16].replace("T", " "))})
            deep = last["stage_share"].get(STAGE_DEEP)
            kpis.append({"label": LABEL_DEEP_SHARE, "value": f"{(deep or 0) * 100:.0f}",
                         "unit": UNIT_PERCENT,
                         "hint": hint_minutes(last["stage_minutes"].get(STAGE_DEEP, 0))})
            kpis.append({"label": LABEL_SLEEP_EFFICIENCY,
                         "value": f"{last['efficiency'] * 100:.0f}", "unit": UNIT_PERCENT,
                         "hint": hint_awakenings(last["awakenings"])})
        else:
            # Without heart rate the band's own sleep window is all we can trust.
            kpis.append({"label": LABEL_LAST_NIGHT_IN_BED,
                         "value": f"{last['minutes_in_bed'] / 60:.1f}",
                         "unit": UNIT_HOURS, "hint": HINT_NO_HR_SLEEP_UNKNOWN})
            for label in (LABEL_DEEP_SHARE, LABEL_SLEEP_EFFICIENCY):
                kpis.append({"label": label, "value": VALUE_PLACEHOLDER,
                             "unit": UNIT_PERCENT, "hint": HINT_NO_HR_DATA})
    else:
        kpis.append({"label": LABEL_LAST_NIGHT_SLEEP, "value": VALUE_PLACEHOLDER,
                     "unit": UNIT_HOURS, "hint": HINT_NO_DATA})
    return kpis


def _averaged_cards(sessions: Sequence[dict], kpi_range: str) -> list[dict[str, str]]:
    """Wider ranges: average the sleep cards over the nights in the window."""
    prefix = RANGE_LABELS.get(kpi_range, kpi_range)
    staged = [s for s in sessions if s["heart_rate_available"]]
    kpis: list[dict[str, str]] = []
    if sessions:
        mean_sleep = statistics.mean(s["minutes_asleep"] for s in sessions) / 60
        kpis.append({"label": LABEL_SLEEP_AVG, "value": f"{mean_sleep:.1f}",
                     "unit": UNIT_HOURS, "hint": f"{prefix} · {hint_nights(len(sessions))}"})
    else:
        kpis.append({"label": LABEL_SLEEP_AVG, "value": VALUE_PLACEHOLDER,
                     "unit": UNIT_HOURS, "hint": f"{prefix} · {HINT_NO_DATA}"})

    if staged:
        deep = statistics.mean(
            s["stage_share"].get(STAGE_DEEP) or 0 for s in staged
        ) * 100
        efficiency = statistics.mean(s["efficiency"] for s in staged) * 100
        kpis.append({"label": LABEL_DEEP_SHARE_AVG, "value": f"{deep:.0f}",
                     "unit": UNIT_PERCENT, "hint": f"{prefix} · {hint_nights(len(staged))}"})
        kpis.append({"label": LABEL_SLEEP_EFFICIENCY_AVG, "value": f"{efficiency:.0f}",
                     "unit": UNIT_PERCENT, "hint": f"{prefix} · {hint_nights(len(staged))}"})
    else:
        for label in (LABEL_DEEP_SHARE_AVG, LABEL_SLEEP_EFFICIENCY_AVG):
            kpis.append({"label": label, "value": VALUE_PLACEHOLDER,
                         "unit": UNIT_PERCENT, "hint": f"{prefix} · {HINT_NO_HR_DATA}"})
    return kpis


def _common_cards(
    activity: Sequence[dict],
    hr_rows: Sequence[tuple[float, int]],
    spo2_rows: Sequence[dict],
    spo2_sleep_rows: Sequence[dict],
    not_worn: Sequence[dict],
    kpi_range: str,
) -> list[dict[str, str]]:
    """Cards whose computation is identical across every range."""
    kpis: list[dict[str, str]] = []
    last_gap = not_worn[-1] if not_worn else None
    max_gap = max(not_worn, key=lambda span: span["minutes"], default=None)
    if max_gap and max_gap["minutes"] >= 120:
        hint = hint_since(max_gap["start"][5:16].replace("T", " "))
        if last_gap is max_gap:
            hint = hint_most_recent(hint)
        kpis.append({"label": LABEL_BAND_NOT_WORN, "value": f"{max_gap['hours']:.1f}",
                     "unit": UNIT_HOURS, "hint": hint})

    total_steps = sum(int(item["steps"]) for item in activity)
    if kpi_range == RANGE_DAY:
        steps_today = 0
        today = datetime.now().strftime(DAY_FORMAT)
        for item in activity:
            if datetime.fromtimestamp(item["ts"]).strftime(DAY_FORMAT) == today:
                steps_today += int(item["steps"])
        kpis.append({"label": LABEL_STEPS_TODAY, "value": f"{steps_today:,}", "unit": UNIT_STEPS,
                     "hint": hint_steps_activity(len(activity), total_steps)})
    else:
        days = len({
            datetime.fromtimestamp(item["ts"]).strftime(DAY_FORMAT) for item in activity
        })
        daily = round(total_steps / days) if days else 0
        prefix = RANGE_LABELS.get(kpi_range, kpi_range)
        kpis.append({"label": LABEL_STEPS_AVG, "value": f"{daily:,}", "unit": UNIT_STEPS,
                     "hint": f"{prefix} · {hint_days(days, total_steps)}"})

    readings = [hr for hr in (_valid_hr(item["heart_rate"]) for item in activity) if hr]
    if not readings:
        readings = [bool(_valid_hr(bpm)) and bpm for _, bpm in hr_rows]
        readings = [value for value in readings if isinstance(value, int)]
    if readings:
        kpis.append({"label": LABEL_HEART_RATE_RANGE, "value": f"{min(readings)}–{max(readings)}",
                     "unit": UNIT_BPM, "hint": hint_hr_mean(statistics.mean(readings))})
    else:
        kpis.append({"label": LABEL_HEART_RATE_RANGE, "value": VALUE_PLACEHOLDER,
                     "unit": UNIT_BPM, "hint": HINT_NO_DATA})

    # Point measurements (0x25) and the night-long sleep stream (0x26) are
    # different series: report the true minimum across both, and spell out the
    # split so nobody reads it as one homogeneous set of readings.
    all_spo2 = [item["spo2"] for item in spo2_rows]
    all_spo2 += [row["spo2"] for row in spo2_sleep_rows]
    if all_spo2:
        kpis.append({"label": LABEL_SPO2_MIN, "value": f"{min(all_spo2)}",
                     "unit": UNIT_PERCENT,
                     "hint": hint_spo2_split(len(spo2_rows), len(spo2_sleep_rows))})
    else:
        kpis.append({"label": LABEL_SPO2_MIN, "value": VALUE_PLACEHOLDER,
                     "unit": UNIT_PERCENT, "hint": HINT_NO_SPO2_RECORDS})
    return kpis


def _kpis(
    sessions: Sequence[dict],
    activity: Sequence[dict],
    spo2_rows: Sequence[dict],
    hr_rows: Sequence[tuple[float, int]],
    not_worn: Sequence[dict] = (),
    spo2_sleep_rows: Sequence[dict] = (),
    *,
    range: str = RANGE_DAY,
) -> list[dict[str, str]]:
    """Build the KPI cards at the requested semantic time *range*.

    ``"day"`` is the historical "last night / today" view; ``week``, ``month``
    and ``all`` average the sleep cards and turn the steps card into a daily
    average.  The range is keyword-only so existing six-argument callers keep
    the exact same report.
    """
    kpi_range = range
    if kpi_range == RANGE_DAY:
        kpis = _last_night_cards(sessions)
    else:
        kpis = _averaged_cards(sessions, kpi_range)
    kpis.extend(_common_cards(activity, hr_rows, spo2_rows, spo2_sleep_rows, not_worn, kpi_range))
    return kpis
