"""B-12: SPORTS_SUMMARIES (0x05) parser regression tests.

The fixture is a real Mi Band 6 workout capture (summary version 519) published
in Gadgetbridge's ``HuamiActivitySummaryParserTest`` (AGPL-3.0, test data only).
Its expected steps/calories/HR values are the ground truth for this parser.
"""

from __future__ import annotations

import pytest

from miband_monitor.history.models import HistoryParseError
from miband_monitor.history.summary_parser import parse_sports_summary
from tests.history.summary_fixture import SUMMARY_V519_RUNNING


def test_v519_capture_decodes_to_the_reference_values():
    summary = parse_sports_summary(bytes.fromhex(SUMMARY_V519_RUNNING))

    assert summary["version"] == 519
    assert summary["kind_code"] == 1 and summary["kind_name"] == "outdoor_running"
    assert summary["ts"] == 1782879293.0
    assert summary["end_ts"] == 1782880894.0
    assert summary["duration_s"] == 1601
    assert summary["steps"] == 4351
    assert summary["active_seconds"] == 1597
    assert summary["calories"] == pytest.approx(359.975, abs=0.2)
    assert summary["distance_m"] == pytest.approx(3211.467, abs=0.2)
    assert summary["average_hr"] == 172
    assert summary["max_hr"] == 187
    assert summary["has_gps"] is False  # Band 6 has no GPS hardware


def test_v519_garbage_sentinels_are_dropped_not_published():
    summary = parse_sports_summary(bytes.fromhex(SUMMARY_V519_RUNNING))
    assert summary["min_hr"] is None       # -256 sentinel
    assert summary["min_pace_s_per_m"] is None  # 277 s/m "paused" sentinel
    assert summary["altitude_max_m"] is None    # -100000 sentinel
    assert summary["altitude_min_m"] is None    # 100000 sentinel


@pytest.mark.parametrize("size", [0, 4])
def test_short_payload_raises_a_parse_error(size):
    with pytest.raises(HistoryParseError):
        parse_sports_summary(bytes(size))


@pytest.mark.parametrize("size", [12, 100, 200])
def test_truncated_payload_raises_a_parse_error(size):
    payload = bytes.fromhex(SUMMARY_V519_RUNNING)[:size]
    with pytest.raises(HistoryParseError, match="truncated"):
        parse_sports_summary(payload)


def test_old_summary_versions_are_refused_with_a_clear_message():
    payload = (7).to_bytes(2, "little") + b"\x00" * 20
    with pytest.raises(HistoryParseError, match="unsupported summary version 7"):
        parse_sports_summary(payload)
