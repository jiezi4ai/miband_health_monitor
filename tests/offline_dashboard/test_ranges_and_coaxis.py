"""B-7/B-8: semantic ranges, co-axis buckets, explicit bands and KPI ranges."""

from __future__ import annotations

import json
import re

import pytest

from history_dashboard import (
    RANGE_CHOICES,
    RANGE_DAYS,
    RANGE_LABELS,
    bucket_seconds,
    collect,
    hypnogram_svg,
    normalize_range,
    package_combined,
    render,
    resolve_ranges,
)
from sleep_analysis import STAGE_AWAKE, STAGE_DEEP, STAGE_UNKNOWN
from tests.offline_dashboard.support import BASE, make_db, nights


# ---------------------------------------------------------------------------
# range semantics
# ---------------------------------------------------------------------------
def test_range_constants_and_validation():
    assert RANGE_CHOICES == ("day", "week", "month", "all")
    assert RANGE_DAYS["day"] == 1 and RANGE_DAYS["week"] == 7
    assert RANGE_DAYS["month"] == 30 and RANGE_DAYS["all"] is None
    assert RANGE_LABELS["all"] == "全库"
    assert normalize_range(None) is None
    with pytest.raises(ValueError, match="unknown range"):
        normalize_range("year")


def test_resolve_ranges_keeps_legacy_days_and_widens_for_kpi():
    selected, kpi, since, days = resolve_ranges(days=14)
    assert (selected, kpi, days) == (None, "day", 14)
    assert since > 0

    selected, kpi, since, days = resolve_ranges("week", "all", 2)
    assert (selected, kpi, days) == ("week", "all", None)
    assert since == 0.0  # the KPI must see the full archive

    selected, kpi, _since, days = resolve_ranges("day", "month", 30)
    assert (selected, kpi, days) == ("day", "month", 30)


def test_collect_range_controls_the_window_and_meta(tmp_path):
    old = (BASE - 20 * 86400, 1, 0, 7, 70)
    path = make_db(tmp_path, activity=[old] + nights())

    full = collect(path, range="all")
    week = collect(path, range="week")
    assert full["meta"]["days"] is None
    assert full["meta"]["range_label"] == "全库"
    assert full["meta"]["kpi_label"] == "全库"
    assert full["meta"]["activity_samples"] == 421
    assert week["meta"]["days"] == 7
    assert week["meta"]["activity_samples"] == 420
    # Night-level KPIs switch to averaged cards at non-day ranges.
    assert full["kpi"][0]["label"] == "平均睡眠时长"
    assert "全库" in full["kpi"][0]["hint"]
    assert week["kpi"][0]["label"] == "平均睡眠时长"


def test_kpi_range_can_be_independent_of_the_chart_window(tmp_path):
    path = make_db(tmp_path, activity=nights() + nights(start=BASE + 86400))

    weekly = collect(path, range="week", kpi_range="week")
    cards = {card["label"]: card for card in weekly["kpi"]}
    assert cards["平均睡眠时长"]["value"] == "7.0"
    assert "2 夜均值" in cards["平均睡眠时长"]["hint"]
    assert "近 7 天" in cards["平均睡眠时长"]["hint"]
    assert "日均步数" in cards and "近 7 天" in cards["日均步数"]["hint"]

    # A wide window with an explicitly narrow KPI range keeps last-night cards.
    last_night = collect(path, range="all", kpi_range="day")
    assert last_night["kpi"][0]["label"] == "最近一晚睡眠"
    assert last_night["meta"]["activity_samples"] == weekly["meta"]["activity_samples"]


# ---------------------------------------------------------------------------
# co-axis packaging
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "range_name,window_days,expected",
    [("day", 1, 600), ("week", 7, 3600), ("month", 30, 86400), ("all", None, 86400)],
)
def test_bucket_width_tracks_granularity(range_name, window_days, expected):
    assert bucket_seconds(range_name, window_days) == expected


def test_combined_buckets_leave_gaps_unset():
    activity = [
        {"ts": BASE, "kind": 1, "intensity": 0, "steps": 10, "heart_rate": 70},
        {"ts": BASE + 600, "kind": 243, "intensity": 0, "steps": 0, "heart_rate": 0},
        {"ts": BASE + 1200, "kind": 1, "intensity": 0, "steps": 5, "heart_rate": 255},
    ]
    points = [[BASE, 1], [BASE + 600, 3], [BASE + 1200, 1]]
    combined = package_combined(activity, [(BASE, 71)], points, 600)
    first, second = combined["points"][:2]

    # Band-side HR wins where present, but a live sample in the same bucket is
    # averaged in rather than silently discarded (70 and 71 -> 70.5).
    assert first[1] == 10 and first[2] == 70.5 and first[3] == 1
    # The nonwear minute is its own bucket: no steps, no HR, and the hatch code
    # outranks activity if a bucket ever mixes the two.
    assert second[1] == 0 and second[2] is None and second[3] == 3
    assert combined["points"][2][1] == 5 and combined["points"][2][3] == 1
    # A bucket created only by a live HR row has no steps and no band at all.
    distant = package_combined([], [(BASE + 3600, 82)], [], 3600)
    assert distant["points"][0][1] is None
    assert distant["points"][0][2] == 82
    assert distant["points"][0][3] is None


def test_collect_ships_a_coordinated_series(tmp_path):
    payload = collect(make_db(tmp_path, activity=nights()), days=7, range="week")
    combined = payload["combined"]
    assert combined["bucket_seconds"] == 3600
    assert combined["points"]
    assert all(len(point) == 4 for point in combined["points"])
    assert any(point[3] is not None for point in combined["points"])


# ---------------------------------------------------------------------------
# hypnogram: not worn / no heart rate / no record are three different facts
# ---------------------------------------------------------------------------
def test_hypnogram_nonwear_strip_and_unknown_are_explicit():
    stages = [STAGE_DEEP] * 3 + [STAGE_UNKNOWN] * 2 + [STAGE_AWAKE] * 3
    flags = [False] * 5 + [True] * 2 + [False] * 1
    svg = hypnogram_svg(stages, nonwear=flags, show_unknown=True)

    assert 'viewBox="0 0 8 50"' in svg
    assert "hypnoNonwearHatch" in svg
    assert '#475569' in svg  # recorded minute without HR
    hatch = re.findall(r'<rect x="(\d+)" y="([\d.]+)" width="(\d+)" height="6" fill="url', svg)
    assert hatch == [("5", "44", "2")]


def test_hypnogram_default_keeps_unstaged_minutes_blank():
    svg = hypnogram_svg([STAGE_UNKNOWN] * 10 + [STAGE_DEEP] * 5)
    assert "hypnoNonwearHatch" not in svg
    assert "#475569" not in svg
    assert 'viewBox="0 0 15 44"' in svg


def test_collect_session_carries_nonwear_flags(tmp_path):
    payload = collect(make_db(tmp_path, activity=nights()), days=7, range="week")
    session = payload["sleep"]["sessions"][0]
    assert len(session["nonwear"]) == len(session["stages"])
    assert "hypnoNonwearHatch" in session["svg"]
    assert "#475569" in session["svg"] or set(session["stages"]) != {STAGE_UNKNOWN}


# ---------------------------------------------------------------------------
# render/CLI
# ---------------------------------------------------------------------------
def test_render_has_coaxis_chart_and_no_placeholders(tmp_path):
    html = render(collect(make_db(tmp_path, activity=nights()), days=7, range="month"))
    assert 'id="coChart"' in html
    assert "function renderCoAxis()" in html
    assert "renderCoAxis();" in html
    assert "__DATA__" not in html and "__STAGE_STYLE__" not in html
    data = json.loads(re.search(r"const DATA = (\{.*?\});\nconst STAGE_COLORS", html, re.S).group(1))
    assert data["meta"]["range_name"] == "month"
    assert data["combined"]["bucket_seconds"] == 86400
