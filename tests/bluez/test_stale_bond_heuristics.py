"""Tests for stale-bond unresolved-drop tracking and follow-up recovery paths."""

from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

from miband_monitor import bluez
from miband_monitor.ble import MiBand6Client
from sim_band import FakeDevice
from tests.support import KEY, MAC


def _patch_stale_bond_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    now: list[float],
    wait_fn,
    paired_present: bool = True,
) -> tuple[list[str], list[bool]]:
    real_sleep = asyncio.sleep
    monkeypatch.setattr("miband_monitor.ble.link.time.monotonic", lambda: now[0])
    monkeypatch.setattr("miband_monitor.ble.bluez_recovery.time.monotonic", lambda: now[0])
    monkeypatch.setattr(bluez, "is_bluez_platform", lambda: True)
    monkeypatch.setattr(bluez, "link_standby_budget", lambda _t: 75.0)
    monkeypatch.setattr(bluez, "make_ble_device", lambda info: info.get("ble"))
    monkeypatch.setattr("miband_monitor.ble.link.asyncio.sleep", lambda _d: real_sleep(0))
    monkeypatch.setattr("miband_monitor.ble.bluez_recovery.asyncio.sleep", lambda _d: real_sleep(0))

    removed: list[str] = []
    agent_started: list[bool] = []
    paired_state = [FakeDevice(MAC) if paired_present else None]

    class FakeAgent:
        def __init__(self, target_address: str) -> None:
            self.target_address = target_address

        async def start(self) -> bool:
            agent_started.append(True)
            return True

    async def fake_remove(addr: str) -> bool:
        removed.append(addr)
        paired_state[0] = None
        return True

    monkeypatch.setattr(bluez, "BlueZPairingAgent", FakeAgent)
    monkeypatch.setattr(bluez, "paired_device", lambda _a: real_sleep(0, result=paired_state[0]))
    monkeypatch.setattr(bluez, "remove_device", fake_remove)
    monkeypatch.setattr(bluez, "wait_for_bluez_link", wait_fn)
    return removed, agent_started


def _make_stub_client() -> MiBand6Client:
    class OkBle:
        async def connect(self) -> None:
            return None

    async def fake_discover(*_a, **_kw):
        return FakeDevice(MAC)

    async def noop(*_a, **_kw) -> None:
        return None

    client = MiBand6Client(MAC, KEY, client_factory=lambda _d, **_kw: OkBle())
    client._discover_device = fake_discover  # type: ignore[method-assign]
    client._ensure_bluez_ready = noop  # type: ignore[method-assign]
    return client


async def test_wait_for_bluez_link_records_unresolved_drop_durations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_time = [0.0]
    real_loop = asyncio.get_running_loop()
    real_sleep = asyncio.sleep
    target_path = bluez.device_path_for_address(MAC)

    class _LoopProxy:
        def time(self) -> float:
            return fake_time[0]

        def __getattr__(self, name: str):
            return getattr(real_loop, name)

    states = iter([
        {"path": target_path, "connected": True, "services_resolved": False},
        {"path": target_path, "connected": False, "services_resolved": False},
        {"path": target_path, "connected": True, "services_resolved": True},
    ])

    class _FakeBus:
        async def connect(self):
            return self

        async def introspect(self, *_args):
            return object()

        def get_proxy_object(self, *_args):
            return SimpleNamespace(
                get_interface=lambda _i: SimpleNamespace(
                    call_get_managed_objects=lambda: real_sleep(0, result={target_path: {}})
                )
            )

        async def call(self, _msg):
            return None

        def disconnect(self) -> None:
            return None

    fake_dbus_fast = types.ModuleType("dbus_fast")
    fake_dbus_fast.BusType = SimpleNamespace(SYSTEM=1)
    fake_dbus_fast.Message = lambda **kw: SimpleNamespace(**kw)
    fake_dbus_aio = types.ModuleType("dbus_fast.aio")
    fake_dbus_aio.MessageBus = lambda **_kw: _FakeBus()

    monkeypatch.setitem(sys.modules, "dbus_fast", fake_dbus_fast)
    monkeypatch.setitem(sys.modules, "dbus_fast.aio", fake_dbus_aio)
    monkeypatch.setattr(bluez, "is_bluez_platform", lambda: True)
    monkeypatch.setattr(bluez.devices, "_info_for_address", lambda _o, _a: next(states))
    monkeypatch.setattr("miband_monitor.bluez.link.asyncio.get_running_loop", _LoopProxy)

    durations_seen: list[float] = []

    async def fake_sleep(delay: float) -> None:
        fake_time[0] += 2.5 if not durations_seen else max(delay, 0.2)
        durations_seen.append(fake_time[0])
        await real_sleep(0)

    monkeypatch.setattr("miband_monitor.bluez.link.asyncio.sleep", fake_sleep)

    outcome = await bluez.wait_for_bluez_link(MAC, timeout=30.0)
    assert outcome["ready"] is True
    assert outcome["dropped_unresolved"] == 1
    assert outcome["unresolved_drop_durations"] == [2.5]


async def test_stale_bond_recovers_after_one_drop_plus_followup_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    call_n = [0]

    async def fake_wait(_addr: str, *, timeout: float, **_kw):
        call_n[0] += 1
        if call_n[0] == 1:
            now[0] += 45.0
            return {
                "ready": False,
                "reason": "connect-timeout",
                "attempts": 2,
                "dropped_unresolved": 1,
                "unresolved_drop_durations": [2.8],
                "errors": ["dropped-unresolved-after-2.8s"],
                "info": None,
            }
        if call_n[0] == 2:
            # Nearly exhaust original budget (< 12 s left) before failing scan link.
            now[0] = 1070.0
            return {
                "ready": False,
                "reason": "connect-timeout",
                "attempts": 1,
                "dropped_unresolved": 0,
                "unresolved_drop_durations": [],
                "errors": ["le-connection-abort-by-local"],
                "info": None,
            }
        return {
            "ready": True,
            "reason": "resolved",
            "attempts": 1,
            "dropped_unresolved": 0,
            "unresolved_drop_durations": [],
            "info": {"ble": FakeDevice(MAC)},
        }

    removed, agent_started = _patch_stale_bond_env(monkeypatch, now=now, wait_fn=fake_wait)
    client = _make_stub_client()

    await client._open_bluez_link(FakeDevice(MAC), scan_timeout=75.0, connect_timeout=75.0)
    assert call_n[0] == 3
    assert removed == [MAC]
    assert agent_started == [True]
    assert client._stale_bond_reset_attempted is True
    assert client._unresolved_drops == 0


async def test_stale_bond_streak_recovers_when_next_attempt_direct_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    call_n = [0]

    async def fake_wait(_addr: str, *, timeout: float, **_kw):
        call_n[0] += 1
        if call_n[0] == 1:
            return {
                "ready": False,
                "reason": "connect-timeout",
                "attempts": 2,
                "dropped_unresolved": 0,
                "errors": ["connect-timeout"],
                "info": None,
            }
        return {
            "ready": True,
            "reason": "resolved",
            "attempts": 1,
            "dropped_unresolved": 0,
            "info": {"ble": FakeDevice(MAC)},
        }

    removed, agent_started = _patch_stale_bond_env(monkeypatch, now=now, wait_fn=fake_wait)
    client = _make_stub_client()
    client._unresolved_drops = 1  # Carried from previous failed session

    await client._open_bluez_link(FakeDevice(MAC), scan_timeout=75.0, connect_timeout=75.0)
    assert removed == [MAC]
    assert agent_started == [True]
    assert call_n[0] == 2


async def test_open_bluez_link_defers_ready_check_until_after_wait_for_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    events: list[object] = []

    async def fake_wait(_addr: str, *, timeout: float, **_kw):
        events.append("wait_for_bluez_link")
        return {
            "ready": True,
            "reason": "resolved",
            "attempts": 1,
            "dropped_unresolved": 0,
            "info": {"ble": FakeDevice(MAC)},
        }

    _patch_stale_bond_env(monkeypatch, now=now, wait_fn=fake_wait)
    client = _make_stub_client()

    async def track_discover(*_a, **_kw):
        events.append("discover")
        return FakeDevice(MAC)

    async def track_ready(device=None) -> None:
        events.append(("ready", getattr(device, "address", None)))

    client._discover_device = track_discover  # type: ignore[method-assign]
    client._ensure_bluez_ready = track_ready  # type: ignore[method-assign]

    await client._open_bluez_link(None, scan_timeout=75.0, connect_timeout=75.0)
    assert events == [("ready", None), "discover", "wait_for_bluez_link", ("ready", MAC)]


async def test_open_bluez_link_marks_scanned_device_trusted_during_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    events: list[object] = []
    real_sleep = asyncio.sleep

    async def fake_wait(_addr: str, *, timeout: float, **_kw):
        events.append("wait_start")
        # Let the background trust task (asyncio.sleep(1.0) patched to 0) finish.
        await real_sleep(0)
        await real_sleep(0)
        events.append("wait_end")
        return {
            "ready": True,
            "reason": "resolved",
            "attempts": 1,
            "dropped_unresolved": 0,
            "info": {"ble": FakeDevice(MAC)},
        }

    _patch_stale_bond_env(monkeypatch, now=now, wait_fn=fake_wait)
    client = _make_stub_client()

    async def track_discover(*_a, **_kw):
        events.append("discover")
        return FakeDevice(MAC)

    async def track_ready(device=None) -> None:
        events.append(("ready", getattr(device, "address", None)))

    client._discover_device = track_discover  # type: ignore[method-assign]
    client._ensure_bluez_ready = track_ready  # type: ignore[method-assign]

    await client._open_bluez_link(None, scan_timeout=75.0, connect_timeout=75.0)
    assert events[:4] == [("ready", None), "discover", "wait_start", ("ready", MAC)]
    assert events[-1] == ("ready", MAC)
    assert "wait_end" in events and events.index(("ready", MAC), 1) < events.index("wait_end")
