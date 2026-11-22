"""PAI (0x0d) parser tests against a real Mi Band 6 capture.

The payload was captured on 2026-11-20 with ``tools/capture_fetch_type.py 0d``
(no ACK, so the band copy stayed intact) and is kept verbatim: it is the only
external evidence for this layout we have.
"""

from __future__ import annotations

import pytest

from miband_monitor.history.models import HistoryParseError
from miband_monitor.history.pai_parser import (
    PAI_RECORD_SIZE,
    pai_components_sum,
    parse_pai,
)

#: Mi Band 6, firmware V1.0.6.20, one snapshot record dated 2026-11-10 23:59:51 +08:00.
PAI_SNAPSHOT = (
    "05773ff36a20000000e3850a3c9ef6373cb537c03cbd73573c5d0f413d6c59583d8c1c573c"
    "00b5f64060fadf4000000000490132000000b0576b41d23548422e00b9000500d2354842"
    "d9df3942e78a3042ed0624422b6a09421673f441e93784410028586f94"
)


def test_snapshot_decodes_to_the_captured_values():
    payload = bytes.fromhex(PAI_SNAPSHOT)
    assert len(payload) == PAI_RECORD_SIZE

    records = parse_pai(payload)
    assert len(records) == 1
    record = records[0]
    assert record["ts"] == 1794326391.0
    assert record["iso_time"] == "2026-11-10T23:59:51+08:00"
    assert record["utc_offset_minutes"] == 480
    assert record["pai_low"] == 7.71
    assert record["pai_moderate"] == 6.999
    assert record["pai_high"] == 0.0
    assert (record["minutes_low"], record["minutes_moderate"], record["minutes_high"]) == (329, 50, 0)
    assert record["pai_total"] == 50.053


def test_pai_today_is_the_sum_of_its_three_components():
    """Self-consistency check: this is what convinced us the offsets are right.

    A misaligned read would produce three floats that do not add up to the
    ``pai_today`` field eight bytes later.
    """
    record = parse_pai(bytes.fromhex(PAI_SNAPSHOT))[0]
    assert pai_components_sum(record) == record["pai_today"] == 14.709


def test_values_match_the_zepp_page_captured_the_same_morning():
    """Zepp Life showed ``50 PAI`` / ``今日共获取 14PAI`` / ``7 / 7 / 0``.

    Compared within one PAI unit instead of by rounding: the app is not
    consistent about it. ``14.709`` is shown as **14** (truncated) while
    ``6.999`` is shown as **7** (rounded up), so no single rounding rule
    reproduces the page -- which is exactly why the check is "agrees to within
    a unit" rather than "formats identically".
    """
    record = parse_pai(bytes.fromhex(PAI_SNAPSHOT))[0]
    shown = {
        "pai_total": 50,
        "pai_today": 14,
        "pai_low": 7,
        "pai_moderate": 7,
        "pai_high": 0,
    }
    for field, printed in shown.items():
        assert abs(record[field] - printed) < 1, field
    assert [record["minutes_low"], record["minutes_moderate"], record["minutes_high"]] == [329, 50, 0]


def test_week_array_repeats_the_total_and_falls_off_day_by_day():
    """The seven floats are the rolling 7-day PAI, newest first.

    ``week[0]`` being bit-identical to ``pai_total`` is what fixes the direction,
    and the monotonic decrease matches the app's seven descending bars
    (11-04 → 11-10).
    """
    record = parse_pai(bytes.fromhex(PAI_SNAPSHOT))[0]
    assert record["pai_week"][0] == record["pai_total"] == 50.053
    assert record["pai_week"] == pytest.approx(
        [50.053, 46.469, 44.136, 41.007, 34.354, 30.556, 16.527], abs=1e-3
    )
    assert record["pai_week"] == sorted(record["pai_week"], reverse=True)


def test_counters_and_tail_are_kept_but_not_interpreted():
    record = parse_pai(bytes.fromhex(PAI_SNAPSHOT))[0]
    assert record["counters"] == [46, 185, 5]
    assert record["unknown_tail"] == "0028586f94"


def test_a_second_capture_seven_days_later_keeps_the_same_invariants():
    """Captured after one Zepp sync: the record moved 11-10 -> 11-17.

    ``counters[0]`` went 46 -> 47 with exactly one new record, and every
    structural invariant survived: same record type, ``pai_today`` still the sum
    of its parts, ``week[0]`` still equal to ``pai_total``, series still
    monotonically decreasing.
    """
    payload = bytes.fromhex(
        "05f679fc6a200000004a29da3c46dbcf3c1057b73c0957f13cd3331b3d749da7"
        "3c04da893d00ae3d4020281440000000009c001300000010eba84059c183422f"
        "00b900050059c18342f96340425ae72242d8110642610bd841dbaa91411831d0"
        "400028586f94"
    )
    assert len(payload) == PAI_RECORD_SIZE
    record = parse_pai(payload)[0]

    assert record["iso_time"] == "2026-11-17T23:59:50+08:00"
    assert record["pai_total"] == 65.878
    assert record["pai_today"] == 5.279
    assert pai_components_sum(record) == record["pai_today"]
    assert record["counters"] == [47, 185, 5]
    assert record["pai_week"][0] == record["pai_total"]
    assert record["pai_week"] == sorted(record["pai_week"], reverse=True)


def test_legacy_type_zero_records_are_dropped():
    """Type 0 means "before a factory reset" -- Gadgetbridge ignores it too."""
    legacy = bytearray(bytes.fromhex(PAI_SNAPSHOT))
    legacy[0] = 0
    payload = bytes(legacy) + bytes.fromhex(PAI_SNAPSHOT)
    assert len(parse_pai(payload)) == 1


def test_empty_payload_yields_nothing():
    assert parse_pai(b"") == []


def test_partial_record_is_a_parse_error():
    payload = bytes.fromhex(PAI_SNAPSHOT)[:50]
    with pytest.raises(HistoryParseError, match="not a multiple"):
        parse_pai(payload)


def test_unknown_type_is_a_parse_error():
    payload = bytearray(bytes.fromhex(PAI_SNAPSHOT))
    payload[0] = 9
    with pytest.raises(HistoryParseError, match="unknown PAI record type 9"):
        parse_pai(bytes(payload))
