"""Tests for BlueZ residual-link cleanup and stale-LTK self-healing."""

from __future__ import annotations

import asyncio
import logging
import sys
import types
from types import SimpleNamespace

import pytest

import miband_monitor.ble.client as _ble_client_module
from miband_monitor import bluez
from miband_monitor.ble.client import MiBand6Client
from miband_monitor.bluez import admin
from miband_monitor.cli.runner import run_monitor
from sim_band import FakeDevice
from tests.support import KEY, MAC


async def test_remove_device_calls_adapter_remove_device(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[object] = []

    class FakeBus:
        async def connect(self): return self
        async def call(self, msg):
            sent.append(msg)
            return SimpleNamespace(message_type=2)
        def disconnect(self) -> None: return None

    fake_dbus_fast = types.ModuleType("dbus_fast")
    fake_dbus_fast.BusType = SimpleNamespace(SYSTEM=1)
    fake_dbus_fast.MessageType = SimpleNamespace(METHOD_RETURN=2)
    fake_dbus_fast.Message = lambda **kw: SimpleNamespace(**kw)
    fake_dbus_aio = types.ModuleType("dbus_fast.aio")
    fake_dbus_aio.MessageBus = lambda **_kw: FakeBus()

    monkeypatch.setitem(sys.modules, "dbus_fast", fake_dbus_fast)
    monkeypatch.setitem(sys.modules, "dbus_fast.aio", fake_dbus_aio)
    monkeypatch.setattr(bluez.platform, "is_bluez_platform", lambda: True)
    target_path = bluez.device_path_for_address(MAC)

    async def fake_find(_addr: str, *, timeout: float = 5.0):
        return {"path": target_path, "address": MAC}

    monkeypatch.setattr(bluez.devices, "find_device", fake_find)

    assert await admin.remove_device(MAC) is True
    assert len(sent) == 1
    assert sent[0].path == "/org/bluez/hci0"
    assert sent[0].interface == bluez.ADAPTER_IFACE
    assert sent[0].member == "RemoveDevice"
    assert sent[0].body == [target_path]

    monkeypatch.setattr(bluez.platform, "is_bluez_platform", lambda: False)
    assert await admin.remove_device(MAC) is False


async def test_wait_for_bluez_link_exits_early_on_two_unresolved_drops(
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
        {"path": target_path, "connected": True, "services_resolved": False},
        {"path": target_path, "connected": False, "services_resolved": False},
    ])

    class _FakeBus:
        async def connect(self): return self
        async def introspect(self, *_args): return object()
        def get_proxy_object(self, *_args):
            return SimpleNamespace(get_interface=lambda _i: SimpleNamespace(
                call_get_managed_objects=lambda: real_sleep(0, result={target_path: {}})
            ))
        async def call(self, _msg) -> None: return None
        def disconnect(self) -> None: return None

    fake_dbus_fast = types.ModuleType("dbus_fast")
    fake_dbus_fast.BusType = SimpleNamespace(SYSTEM=1)
    fake_dbus_fast.Message = lambda **kw: SimpleNamespace(**kw)
    fake_dbus_aio = types.ModuleType("dbus_fast.aio")
    fake_dbus_aio.MessageBus = lambda **_kw: _FakeBus()

    monkeypatch.setitem(sys.modules, "dbus_fast", fake_dbus_fast)
    monkeypatch.setitem(sys.modules, "dbus_fast.aio", fake_dbus_aio)
    monkeypatch.setattr(bluez, "is_bluez_platform", lambda: True)
    monkeypatch.setattr(bluez.devices, "_info_for_address", lambda _objs, _addr: next(states))
    monkeypatch.setattr("miband_monitor.bluez.link.asyncio.get_running_loop", _LoopProxy)

    async def fake_sleep(delay: float) -> None:
        fake_time[0] += max(delay, 0.5)
        await real_sleep(0)

    monkeypatch.setattr("miband_monitor.bluez.link.asyncio.sleep", fake_sleep)

    outcome = await bluez.wait_for_bluez_link(MAC, timeout=60.0)
    assert outcome["ready"] is False
    assert outcome["reason"] == "dropped-unresolved"
    assert outcome["dropped_unresolved"] == 2
    assert fake_time[0] < 10.0


async def test_ghost_connection_cleared_and_reused_failure_disconnects(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class DummyBle:
        def __init__(self, dev, **_kw):
            self.address = getattr(dev, "address", MAC)

        async def connect(self) -> None:
            raise OSError("reused socket wedged")

        async def disconnect(self) -> None:
            return None

    monkeypatch.setattr(_ble_client_module, "BleakClient", DummyBle)
    monkeypatch.setattr(bluez, "is_bluez_platform", lambda: True)

    disconnect_calls: list[str] = []

    async def fake_disconnect(addr: str) -> bool:
        disconnect_calls.append(addr)
        return True

    monkeypatch.setattr(bluez, "connected_device", lambda _a: asyncio.sleep(0, result=None))
    monkeypatch.setattr(bluez, "disconnect_device", fake_disconnect)
    monkeypatch.setattr(bluez, "paired_device", lambda _a: asyncio.sleep(0, result=FakeDevice(MAC)))

    caplog.set_level(logging.WARNING, logger="MiBand6Client")
    client = MiBand6Client(MAC, KEY, client_factory=DummyBle)
    dev = await client._direct_connect_target()
    assert dev is not None
    assert client._reused_bluez_link is False
    assert disconnect_calls == [MAC]
    assert any("ghost BlueZ connection" in rec.message for rec in caplog.records)

    # Reused link setup failure in connect_and_authenticate clears residual BlueZ link.
    client._reused_bluez_link = True

    async def noop(*_a, **_kw) -> None:
        return None

    async def broken_settle() -> None:
        raise ConnectionError("stale reused socket")

    monkeypatch.setattr(client, "_direct_connect_target", lambda: asyncio.sleep(0, result=FakeDevice(MAC)))
    monkeypatch.setattr(client, "_open_client", noop)
    monkeypatch.setattr(client, "_settle_after_link", broken_settle)

    with pytest.raises(ConnectionError):
        await client.connect_and_authenticate()
    assert disconnect_calls == [MAC, MAC]
    assert client._reused_bluez_link is False


async def test_consecutive_dropped_unresolved_triggers_bonded_self_healing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    real_sleep = asyncio.sleep
    monkeypatch.setattr("miband_monitor.ble.link.time.monotonic", lambda: now[0])
    monkeypatch.setattr(bluez, "is_bluez_platform", lambda: True)
    monkeypatch.setattr(bluez, "link_standby_budget", lambda _t: 75.0)
    monkeypatch.setattr(bluez, "make_ble_device", lambda info: info.get("ble"))
    monkeypatch.setattr("miband_monitor.ble.link.asyncio.sleep", lambda _d: real_sleep(0))

    removed: list[str] = []
    agent_started: list[bool] = []
    paired_state = [FakeDevice(MAC)]

    class FakeAgent:
        def __init__(self, target_address: str) -> None:
            self.target_address = target_address

        async def start(self) -> bool:
            agent_started.append(True)
            return True

    monkeypatch.setattr(bluez, "BlueZPairingAgent", FakeAgent)
    monkeypatch.setattr(bluez, "paired_device", lambda _a: real_sleep(0, result=paired_state[0]))

    async def fake_remove(addr: str) -> bool:
        removed.append(addr)
        paired_state[0] = None
        return True

    monkeypatch.setattr(bluez, "remove_device", fake_remove)

    call_n = [0]

    async def fake_wait(_addr: str, *, timeout: float, **_kw):
        call_n[0] += 1
        if call_n[0] == 1:
            return {
                "ready": False,
                "reason": "dropped-unresolved",
                "attempts": 2,
                "dropped_unresolved": 2,
                "errors": ["dropped-unresolved-after-5.1s"],
                "info": None,
            }
        return {
            "ready": True,
            "reason": "resolved",
            "attempts": 1,
            "dropped_unresolved": 0,
            "info": {"ble": FakeDevice(MAC)},
        }

    monkeypatch.setattr(bluez, "wait_for_bluez_link", fake_wait)

    class OkBle:
        async def connect(self) -> None:
            return None

    client = MiBand6Client(MAC, KEY, client_factory=lambda _d, **_kw: OkBle())
    client._trusted_paths.add("/org/bluez/hci0/dev_C0_FF_EE_C0_FF_EE")
    monkeypatch.setattr(client, "_discover_device", lambda *_a, **_kw: real_sleep(0, result=FakeDevice(MAC)))
    monkeypatch.setattr(client, "_ensure_bluez_ready", lambda *_a, **_kw: real_sleep(0))

    await client._open_bluez_link(FakeDevice(MAC), scan_timeout=75.0, connect_timeout=75.0)
    assert removed == [MAC]
    assert agent_started == [True]
    assert client._stale_bond_reset_attempted is True
    assert client._unresolved_drops == 0
    assert client._trusted_paths == set()

    # Unpaired device with consecutive drops must NOT call remove_device.
    call_n[0] = 0
    unpaired = MiBand6Client(MAC, KEY, client_factory=lambda _d, **_kw: OkBle())
    monkeypatch.setattr(unpaired, "_discover_device", lambda *_a, **_kw: real_sleep(0, result=FakeDevice(MAC)))
    monkeypatch.setattr(unpaired, "_ensure_bluez_ready", lambda *_a, **_kw: real_sleep(0))
    await unpaired._open_bluez_link(FakeDevice(MAC), scan_timeout=75.0, connect_timeout=75.0)
    assert removed == [MAC]
    assert unpaired._stale_bond_reset_attempted is False


async def test_run_monitor_carries_unresolved_drop_streak_across_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_initial: list[int] = []

    class FakeClient:
        def __init__(self, _mac: str, _key: str) -> None:
            self._unresolved_drops = 0
            self._stale_bond_reset_attempted = False
            self._auto_enable_pairing_agent = False

        async def connect_and_authenticate(self, **_kw) -> None:
            seen_initial.append(self._unresolved_drops)
            self._unresolved_drops += 1
            if self._unresolved_drops < 2:
                raise TimeoutError("1 unresolved drop")
            self._stale_bond_reset_attempted = True

        async def start_heart_rate_stream(self, _cb) -> None:
            return None

        async def start_steps_stream(self, _cb) -> None:
            return None

        async def wait_until_disconnected(self) -> None:
            await asyncio.sleep(0.05)

        async def disconnect(self) -> None:
            return None

    await run_monitor(
        MAC,
        KEY,
        duration=0.02,
        reconnect=True,
        reconnect_initial_delay=0.0,
        client_factory=FakeClient,
    )
    assert seen_initial == [0, 1]
