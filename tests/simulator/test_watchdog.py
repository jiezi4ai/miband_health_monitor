"""Tests for dual-layer HR silence watchdog and optional 0x2A19 battery probing."""

from __future__ import annotations

import asyncio

import pytest

from miband_monitor.ble import MiBand6Client, StreamCallbacks, parse_battery_level
from miband_monitor.cli.runner import run_monitor
from miband_monitor.simulator import FakeBleakScanner, SimulatedBand, simulated_factories
from tests.support import AUTH_KEY_BYTES, KEY, MAC


def test_parse_battery_level_valid_and_invalid() -> None:
    assert parse_battery_level(b"\x55") == 85
    assert parse_battery_level(b"\x00") == 0
    assert parse_battery_level(b"\x64") == 100
    with pytest.raises(ValueError):
        parse_battery_level(b"")
    with pytest.raises(ValueError):
        parse_battery_level(b"\xff")


@pytest.mark.asyncio
async def test_soft_rearm_resurrects_stalled_hr_without_disconnect() -> None:
    band = SimulatedBand(
        auth_key=AUTH_KEY_BYTES,
        hr_values=(74, 76),
        continuous_interval=0.02,
        freeze_hr_after=2,
        resurrect_on_rearm=True,
    )
    client_factory, _ = simulated_factories(band)

    class _Scanner(FakeBleakScanner):
        default_address = MAC

    client = MiBand6Client(
        MAC,
        KEY,
        client_factory=client_factory,
        scanner_factory=_Scanner,
        keepalive_interval=0.03,
        hr_silence_soft_seconds=0.05,
        hr_silence_hard_seconds=0.40,
        hr_soft_rearm_max=2,
    )
    received: list[int] = []
    await client.connect_and_authenticate(scan_timeout=2.0)
    try:
        await client.start_heart_rate_stream(received.append)
        await asyncio.sleep(0.22)
        assert not client.disconnected_event.is_set()
        assert len(received) >= 3
        # Initial start write + at least one Tier-1 soft re-arm write
        assert band.hr_control_writes.count(b"\x15\x01\x01") >= 2
        assert b"\x16" in band.hr_control_writes
        assert band.connect_count == 1
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_hard_watchdog_triggers_fast_reconnect_after_soft_rearms() -> None:
    band = SimulatedBand(
        auth_key=AUTH_KEY_BYTES,
        hr_values=(140, 142),
        continuous_interval=0.02,
        freeze_hr_after=2,
        freeze_on_connections=(1,),
        resurrect_on_rearm=False,
    )
    client_factory, _ = simulated_factories(band)

    class _Scanner(FakeBleakScanner):
        default_address = MAC

    def _make(mac: str, key: str) -> MiBand6Client:
        return MiBand6Client(
            mac,
            key,
            client_factory=client_factory,
            scanner_factory=_Scanner,
            keepalive_interval=0.03,
            hr_silence_soft_seconds=0.04,
            hr_silence_hard_seconds=0.11,
            hr_soft_rearm_max=2,
        )

    received: list[int] = []
    await run_monitor(
        MAC,
        KEY,
        duration=0.75,
        callbacks=StreamCallbacks(heart_rate=received.append),
        reconnect=True,
        reconnect_initial_delay=0.02,
        client_factory=_make,
    )
    assert band.connect_count >= 2
    assert len(received) >= 4
    assert band.hr_control_writes.count(b"\x15\x01\x01") >= 3


@pytest.mark.asyncio
async def test_off_wrist_zero_hr_packets_keep_watchdog_alive() -> None:
    band = SimulatedBand(
        auth_key=AUTH_KEY_BYTES,
        hr_values=(0,),
        continuous_interval=0.02,
    )
    client_factory, _ = simulated_factories(band)

    class _Scanner(FakeBleakScanner):
        default_address = MAC

    client = MiBand6Client(
        MAC,
        KEY,
        client_factory=client_factory,
        scanner_factory=_Scanner,
        keepalive_interval=0.03,
        hr_silence_soft_seconds=0.05,
        hr_silence_hard_seconds=0.09,
    )
    await client.connect_and_authenticate(scan_timeout=2.0)
    try:
        await client.start_heart_rate_stream()
        await asyncio.sleep(0.16)
        assert not client.disconnected_event.is_set()
        assert band.hr_control_writes.count(b"\x15\x01\x01") == 1
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_battery_probe_supported_and_unsupported() -> None:
    for level, expected in ((85, 85), (None, None)):
        band = SimulatedBand(auth_key=AUTH_KEY_BYTES, battery_level=level)
        client_factory, _ = simulated_factories(band)

        class _Scanner(FakeBleakScanner):
            default_address = MAC

        client = MiBand6Client(
            MAC, KEY, client_factory=client_factory, scanner_factory=_Scanner
        )
        await client.connect_and_authenticate(scan_timeout=2.0)
        try:
            assert await client.read_battery_level() == expected
            if expected is None:
                assert client._battery_supported is False
                assert await client.read_battery_level() is None
            assert not client.disconnected_event.is_set()
        finally:
            await client.disconnect()
