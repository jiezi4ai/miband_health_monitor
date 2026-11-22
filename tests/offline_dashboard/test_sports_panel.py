"""B-12: workout summaries flow into the offline dashboard payload and page."""

from __future__ import annotations

from history_dashboard import collect, render
from tests.offline_dashboard.support import BASE, make_db


def test_collect_includes_band_side_workout_summaries(tmp_path):
    payload = collect(make_db(tmp_path, summaries=[BASE]), days=7, range="week")
    sports = payload["sports"]
    assert payload["meta"]["summary_count"] == 1
    assert sports[0]["kind_name"] == "outdoor_running"
    assert sports[0]["steps"] == 4351
    assert sports[0]["duration_s"] == 1600
    assert sports[0]["start"].startswith("11-")
    assert sports[0]["end"]


def test_page_has_a_workout_summary_table(tmp_path):
    html = render(collect(make_db(tmp_path, summaries=[BASE]), days=7))
    assert 'id="sportsPanel"' in html
    assert "function renderSports()" in html
    assert "renderSports();" in html
    assert "outdoor_running" in html


def test_empty_summary_table_renders_the_sync_hint(tmp_path):
    html = render(collect(make_db(tmp_path), days=7))
    assert "没有手环侧运动总结" in html
    assert "--sync-sports" in html
