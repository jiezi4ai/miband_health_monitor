"""B-10: Mi Band Current Time (0x2A2B) encoding, drift read and safe write."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from miband_monitor.ble.time_sync import (
    UUID_CHAR_CURRENT_TIME,
    TimeSyncMixin,
    decode_current_time,
    encode_current_time,
    maybe_sync_time,
)

CST = timezone(timedelta(hours=8))


class _FakeBle:
    def __init__(self, raw=None, *, read_error=None, write_error=None):
        self.raw = raw
        self.read_error = read_error
        self.write_error = write_error
        self.writes = []

    async def read_gatt_char(self, uuid):
        assert uuid == UUID_CHAR_CURRENT_TIME
        if self.read_error:
            raise self.read_error
        return self.raw

    async def write_gatt_char(self, uuid, data, response=True):
        assert uuid == UUID_CHAR_CURRENT_TIME
        self.writes.append((bytes(data), response))
        if self.write_error:
            raise self.write_error


class _Band(TimeSyncMixin):
    def __init__(self, ble):
        self.client = ble
        self._gatt_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# codec
# ---------------------------------------------------------------------------
def test_encode_matches_the_mi_band_11_byte_layout():
    moment = datetime(2026, 11, 20, 9, 30, 15, tzinfo=CST)  # Friday
    raw = encode_current_time(moment, tz=CST)
    assert len(raw) == 11
    # year LE16, month, day, hour, minute, second, dow=5, 0, 0, +08:00 (32 quarters)
    assert raw.hex() == "ea070b14091e0f05000020"


def test_decode_roundtrip_preserves_wall_clock_and_offset():
    moment = datetime(2026, 11, 20, 9, 30, 15, tzinfo=CST)
    decoded = decode_current_time(encode_current_time(moment, tz=CST))
    assert decoded is not None
    assert decoded.replace(tzinfo=None) == moment.replace(tzinfo=None)
    assert decoded.utcoffset() == timedelta(hours=8)


def test_sunday_maps_to_seven():
    sunday = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    assert encode_current_time(sunday, tz=timezone.utc)[7] == 7


def test_decode_rejects_zeroed_and_short_records():
    assert decode_current_time(b"\x00" * 10) is None
    assert decode_current_time(b"\x01\x02") is None


# ---------------------------------------------------------------------------
# drift / write
# ---------------------------------------------------------------------------
async def test_dry_run_reports_drift_without_writing():
    host = datetime.now(CST)
    ble = _FakeBle(encode_current_time(host - timedelta(seconds=3), tz=CST))
    result = await _Band(ble).sync_current_time(dry_run=True, tz=CST)

    assert result["supported"] is True and result["wrote"] is False
    assert 2.5 <= result["drift_seconds"] <= 4.5
    assert ble.writes == []


async def test_apply_writes_then_re_reads():
    host = datetime.now(CST)
    ble = _FakeBle(encode_current_time(host - timedelta(seconds=5), tz=CST))
    result = await _Band(ble).sync_current_time(tz=CST)

    assert result["wrote"] is True and result["error"] is None
    assert ble.writes and ble.writes[0][1] is True
    assert decode_current_time(ble.writes[0][0]) is not None
    assert result["after"]


async def test_write_failure_is_non_fatal_and_falls_back_to_write_without_response():
    ble = _FakeBle(encode_current_time(datetime.now(CST), tz=CST), write_error=RuntimeError("nope"))
    result = await _Band(ble).sync_current_time(tz=CST)

    assert result["wrote"] is False
    assert "nope" in result["error"]
    assert [response for _, response in ble.writes] == [True, False]


async def test_unreadable_characteristic_is_reported_not_raised():
    ble = _FakeBle(read_error=RuntimeError("characteristic not found"))
    result = await _Band(ble).sync_current_time(dry_run=True, tz=CST)
    assert result["supported"] is False
    assert result["before"] is None


async def test_maybe_sync_time_tolerates_a_client_without_the_mixin():
    result = await maybe_sync_time(object(), dry_run=True)
    assert result["supported"] is False and "no time-sync" in result["error"]


# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------
def test_cli_time_sync_flags_are_mutually_exclusive():
    from miband_client import parse_args
    from miband_monitor.cli.time_args import time_sync_mode

    args = parse_args(["--demo", "1", "--sync-time"])
    assert time_sync_mode(args) == "apply"
    args = parse_args(["--demo", "1", "--sync-time-dry-run"])
    assert time_sync_mode(args) == "dry-run"
    assert time_sync_mode(parse_args(["--demo", "1"])) is None

    with pytest.raises(SystemExit):
        parse_args(["--sync-time", "--sync-time-dry-run"])
