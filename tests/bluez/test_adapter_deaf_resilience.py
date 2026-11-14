"""Tests for zero-packet AdapterDeafError detection and supervisor fail-fast."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

import miband_monitor.ble.discovery as disc_mod
from miband_monitor.ble import AdapterDeafError, MiBand6Client
from miband_monitor.cli.runner import run_monitor
from miband_monitor.config.defaults import DEFAULT_SCAN_SILENCE_WARNING_SECONDS
from tests.support import KEY, MAC


async def test_discover_device_distinguishes_deaf_adapter_from_quiet_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _make_scanner(emit_other: bool):
        class _Scanner:
            def __init__(self, *, detection_callback, **_kw) -> None:
                self._cb = detection_callback

            async def start(self) -> None:
                if emit_other:
                    self._cb(SimpleNamespace(address="11:22:33:44:55:66", name="Other"), None)

            async def stop(self) -> None:
                return None

        return _Scanner

    async def fast_timeout(awaitable, timeout=None):
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(disc_mod.asyncio, "wait_for", fast_timeout)
    silence_wait = float(DEFAULT_SCAN_SILENCE_WARNING_SECONDS) + 1.0

    client_deaf = MiBand6Client(MAC, KEY, scanner_factory=_make_scanner(False))
    with pytest.raises(AdapterDeafError) as excinfo:
        await client_deaf._discover_device(silence_wait)
    assert isinstance(excinfo.value, TimeoutError)
    assert client_deaf._last_scan_stats == {"band": 0, "other": 0, "wait_for": silence_wait}

    client_other = MiBand6Client(MAC, KEY, scanner_factory=_make_scanner(True))
    with pytest.raises(TimeoutError) as plain_exc:
        await client_other._discover_device(silence_wait)
    assert not isinstance(plain_exc.value, AdapterDeafError)
    assert client_other._last_scan_stats == {"band": 0, "other": 1, "wait_for": silence_wait}


async def test_run_monitor_aborts_early_on_adapter_deaf_streak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    observed_direct: list[bool] = []
    disconnects = [0]

    class AlwaysDeafClient:
        def __init__(self, _mac: str, _key: str) -> None:
            self._direct_connect = True
            self._unresolved_drops = 0
            self._stale_bond_reset_attempted = False
            self._auto_enable_pairing_agent = False

        async def connect_and_authenticate(self, **_kw) -> None:
            observed_direct.append(self._direct_connect)
            if len(observed_direct) == 1:
                self._unresolved_drops = 1
            raise AdapterDeafError("0 BLE packets across 90s", silence_seconds=90.0)

        async def disconnect(self) -> None:
            disconnects[0] += 1

    caplog.set_level(logging.ERROR, logger="MiBand6Client")
    with pytest.raises(AdapterDeafError):
        await run_monitor(
            MAC,
            KEY,
            duration=600,
            reconnect=True,
            reconnect_initial_delay=0.0,
            adapter_deaf_limit=2,
            client_factory=AlwaysDeafClient,
        )

    assert observed_direct == [True, False]
    assert disconnects[0] == 2
    assert any("consecutive 0-packet scans" in rec.message for rec in caplog.records)


async def test_run_monitor_keeps_active_session_alive_after_mid_workout_deaf_streak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempts = [0]
    disconnects = [0]

    class MidWorkoutDeafClient:
        def __init__(self, _mac: str, _key: str) -> None:
            self._direct_connect = True
            self._unresolved_drops = 0
            self._stale_bond_reset_attempted = False
            self._auto_enable_pairing_agent = False

        async def connect_and_authenticate(self, **_kw) -> None:
            attempts[0] += 1
            if attempts[0] in (1, 4):
                return None
            raise AdapterDeafError("0 BLE packets across 90s", silence_seconds=90.0)

        async def start_heart_rate_stream(self, _cb) -> None:
            return None

        async def start_steps_stream(self, _cb) -> None:
            return None

        async def wait_until_disconnected(self) -> None:
            if attempts[0] == 1:
                return None
            await asyncio.sleep(0.2)

        async def disconnect(self) -> None:
            disconnects[0] += 1

    caplog.set_level(logging.ERROR, logger="MiBand6Client")
    await run_monitor(
        MAC,
        KEY,
        duration=0.05,
        reconnect=True,
        reconnect_initial_delay=0.0,
        adapter_deaf_limit=2,
        client_factory=MidWorkoutDeafClient,
    )

    assert attempts[0] == 4
    assert disconnects[0] == 4
    assert any("since disconnect" in rec.message for rec in caplog.records)
