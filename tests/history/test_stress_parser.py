"""Automatic-stress (0x13) parser tests.

The 24-byte slice is taken verbatim from a real 5761-byte Mi Band 6 capture
(2026-11-20, ``tools/capture_fetch_type.py 13 --days 7``), at byte offset 171.
"""

from __future__ import annotations

import pytest

from miband_monitor.history.models import HistoryParseError
from miband_monitor.history.stress_parser import (
    NO_READING,
    UNMEASURED,
    band_of,
    coverage,
    parse_stress_auto,
)

#: Real slice: 41, 4x unmeasured, 40, 4x unmeasured, 0xFF, 47, 4x unmeasured, 41,
#: 2x unmeasured, 0xFF, 46, unmeasured, 0xFF, 41
REAL_SLICE = bytes.fromhex("29 fe fe fe fe 28 fe fe fe fe ff 2f fe fe fe fe 29 fe fe ff 2e fe ff 29")
BASE = 1_767_000_000.0


def test_real_slice_keeps_only_the_six_scored_minutes():
    samples = parse_stress_auto(REAL_SLICE, BASE)
    assert [sample["stress"] for sample in samples] == [41, 40, 47, 41, 46, 41]
    assert [sample["band"] for sample in samples] == ["mild"] * 6
    # First score is minute 0, the second one is minute 5 -- the gap is real data,
    # not an index bug.
    assert samples[0]["ts"] == BASE
    assert samples[1]["ts"] == BASE + 5 * 60


def test_both_sentinels_are_dropped_not_scored_as_zero():
    """0xFF means "not worn", 0xFE is a marker Gadgetbridge would show as 254."""
    payload = bytes([NO_READING, UNMEASURED, 0, 30, 100])
    samples = parse_stress_auto(payload, BASE)
    # 0 is a valid relaxed score, so only the two sentinels disappear.
    assert [sample["stress"] for sample in samples] == [0, 30, 100]


def test_timestamps_advance_one_minute_per_byte_including_sentinels():
    payload = bytes([50, NO_READING, UNMEASURED, 60])
    samples = parse_stress_auto(payload, BASE)
    assert [sample["ts"] - BASE for sample in samples] == [0, 3 * 60]


def test_values_above_one_hundred_are_a_layout_error():
    with pytest.raises(HistoryParseError, match="exceeds 100"):
        parse_stress_auto(bytes([120]), BASE)


def test_bands_match_zepps_four_buckets():
    assert [band_of(value) for value in (0, 39, 40, 59, 60, 79, 80, 100)] == [
        "relaxed", "relaxed", "mild", "mild", "moderate", "moderate", "high", "high",
    ]
    with pytest.raises(ValueError, match="out of range"):
        band_of(101)


def test_coverage_reports_how_much_of_the_window_was_measured():
    assert coverage(REAL_SLICE) == pytest.approx(6 / 24, abs=1e-4)
    assert coverage(b"") is None
