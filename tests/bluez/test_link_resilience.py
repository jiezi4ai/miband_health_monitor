"""Tests for Plan B BlueZ link resilience fixes."""

from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

from miband_monitor import bluez
from miband_monitor.ble.bluez_recovery import handle_bluez_standby_failure
from miband_monitor.ble.client import MiBand6Client
from miband_monitor.config.defaults import DEFAULT_CONNECT_TIMEOUT, DEFAULT_SCAN_TIMEOUT
from sim_band import FakeDevice
from tests.support import KEY, MAC


def _install_dbus_stub(monkeypatch: pytest.MonkeyPatch, call_fn, *, target_path: str) -> list[str]:
    """Register minimal dbus_fast stubs with a custom async Device1.Connect call."""
    members: list[str] = []

    class _FakeManager:
        async def call_get_managed_objects(self) -> dict:
            return {target_path: {}}

    class _FakeProxy:
        def get_interface(self, _iface: str) -> _FakeManager:
            return _FakeManager()

    class _FakeBus:
        async def connect(self):
            return self

        async def introspect(self, *_args):
            return object()

        def get_proxy_object(self, *_args) -> _FakeProxy:
            return _FakeProxy()

        async def call(self, msg) -> None:
            members.append(getattr(msg, "member", ""))
            return await call_fn(msg)

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
    return members


def test_default_timeouts_cover_measured_band_pulse_period() -> None:
    assert DEFAULT_SCAN_TIMEOUT >= 120.0
    assert DEFAULT_CONNECT_TIMEOUT >= 120.0
    assert bluez.BAND_PULSE_PERIOD >= 90.0


@pytest.mark.asyncio
async def test_wait_for_bluez_link_does_not_rearm_after_abort_with_short_remainder(
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

    async def slow_abort_call(_msg) -> None:
        fake_time[0] += bluez.LE_CONN_TIMEOUT
        raise RuntimeError("org.bluez.Error.Failed: le-connection-abort-by-local")

    members = _install_dbus_stub(monkeypatch, slow_abort_call, target_path=target_path)
    monkeypatch.setattr(
        bluez.devices,
        "_info_for_address",
        lambda _objs, _addr: {
            "path": target_path,
            "connected": False,
            "services_resolved": False,
        },
    )
    monkeypatch.setattr("miband_monitor.bluez.link.asyncio.get_running_loop", _LoopProxy)

    async def fake_sleep(delay: float) -> None:
        fake_time[0] += delay
        await real_sleep(0)

    monkeypatch.setattr("miband_monitor.bluez.link.asyncio.sleep", fake_sleep)

    outcome = await bluez.wait_for_bluez_link(MAC, timeout=bluez.LE_CONN_TIMEOUT + 2.0)
    assert outcome["reason"] == "connect-timeout"
    assert outcome["attempts"] == 1
    assert members == ["Connect"]


@pytest.mark.asyncio
async def test_wait_for_bluez_link_grants_in_flight_connect_grace_at_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_time = [0.0]
    real_loop = asyncio.get_running_loop()
    real_sleep = asyncio.sleep
    target_path = bluez.device_path_for_address(MAC)
    connect_calls = [0]
    cancelled_in_flight = [False]

    class _LoopProxy:
        def time(self) -> float:
            return fake_time[0]

        def __getattr__(self, name: str):
            return getattr(real_loop, name)

    async def call_fn(_msg) -> None:
        connect_calls[0] += 1
        if connect_calls[0] == 1:
            raise RuntimeError("org.bluez.Error.InProgress: Operation already in progress")
        try:
            while fake_time[0] < 41.5:
                await real_sleep(0)
        except asyncio.CancelledError:
            cancelled_in_flight[0] = True
            raise
        raise RuntimeError("org.bluez.Error.Failed: le-connection-abort-by-local")

    _install_dbus_stub(monkeypatch, call_fn, target_path=target_path)
    monkeypatch.setattr(
        bluez.devices,
        "_info_for_address",
        lambda _objs, _addr: {
            "path": target_path,
            "connected": False,
            "services_resolved": False,
        },
    )
    monkeypatch.setattr("miband_monitor.bluez.link.asyncio.get_running_loop", _LoopProxy)

    async def fake_sleep(delay: float) -> None:
        fake_time[0] += max(delay, 5.0)
        await real_sleep(0)

    monkeypatch.setattr("miband_monitor.bluez.link.asyncio.sleep", fake_sleep)

    outcome = await bluez.wait_for_bluez_link(MAC, timeout=40.0)
    assert outcome["reason"] == "connect-timeout"
    assert cancelled_in_flight[0] is False
    assert outcome["attempts"] == 2


@pytest.mark.asyncio
async def test_open_bluez_link_caps_direct_slice_to_single_kernel_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_timeouts: list[float] = []
    now = [1000.0]

    monkeypatch.setattr("miband_monitor.ble.link.time.monotonic", lambda: now[0])
    monkeypatch.setattr(bluez, "is_bluez_platform", lambda: True)
    monkeypatch.setattr(bluez, "link_standby_budget", lambda _t: 120.0)
    monkeypatch.setattr(bluez, "make_ble_device", lambda info: info.get("ble"))

    async def fake_wait_for_link(_addr: str, *, timeout: float, **_kw) -> dict:
        observed_timeouts.append(timeout)
        if len(observed_timeouts) == 1:
            now[0] += 40.0
            return {"ready": False, "reason": "connect-timeout", "attempts": 1, "info": None}
        return {
            "ready": True,
            "reason": "resolved",
            "attempts": 1,
            "info": {"ble": SimpleNamespace(address=MAC)},
        }

    monkeypatch.setattr(bluez, "wait_for_bluez_link", fake_wait_for_link)

    class _FakeBle:
        async def connect(self) -> None:
            return None

    client = MiBand6Client(MAC, KEY, client_factory=lambda _d, **_kw: _FakeBle())
    monkeypatch.setattr(client, "_discover_device", lambda *_a, **_kw: asyncio.sleep(0, result=FakeDevice(MAC)))
    monkeypatch.setattr(client, "_ensure_bluez_ready", lambda *_a, **_kw: asyncio.sleep(0))

    await client._open_bluez_link(FakeDevice(MAC), scan_timeout=120.0, connect_timeout=120.0)
    assert observed_timeouts[0] == bluez.LE_CONN_TIMEOUT + 2.0


@pytest.mark.asyncio
async def test_connect_and_authenticate_auto_enables_agent_when_unbonded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[bool] = []

    class _FakeAgent:
        def __init__(self, _addr: str) -> None:
            self.target_address = ""

        async def start(self) -> bool:
            started.append(True)
            return True

    monkeypatch.setattr(bluez, "is_bluez_platform", lambda: True)
    monkeypatch.setattr(bluez, "BlueZPairingAgent", _FakeAgent)

    class _FakeBleak:
        pass

    async def _wire_client(c: MiBand6Client) -> None:
        c._bleak_client_class = _FakeBleak
        c._client_factory = _FakeBleak
        monkeypatch.setattr(c, "_direct_connect_target", lambda: asyncio.sleep(0, result=None))
        monkeypatch.setattr(c, "_open_client", lambda *_a, **_kw: asyncio.sleep(0))
        monkeypatch.setattr(c, "_prepare_and_authenticate", lambda *_a, **_kw: asyncio.sleep(0))

    monkeypatch.delenv("MIBAND_BLUEZ_AGENT", raising=False)
    c1 = MiBand6Client(MAC, KEY)
    await _wire_client(c1)
    await c1.connect_and_authenticate()
    assert started == [True]

    started.clear()
    monkeypatch.setenv("MIBAND_BLUEZ_AGENT", "0")
    c2 = MiBand6Client(MAC, KEY)
    await _wire_client(c2)
    await c2.connect_and_authenticate()
    assert started == []


@pytest.mark.asyncio
async def test_handle_bluez_standby_failure_clears_half_paired_services_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[str] = []
    started: list[bool] = []

    class _FakeAgent:
        def __init__(self, _addr: str) -> None:
            self.target_address = ""

        async def start(self) -> bool:
            started.append(True)
            return True

    monkeypatch.setattr(bluez, "BlueZPairingAgent", _FakeAgent)
    monkeypatch.setattr(bluez, "remove_device", lambda addr: (removed.append(addr), asyncio.sleep(0, result=True))[1])

    client = MiBand6Client(MAC, KEY, client_factory=lambda *_a, **_kw: None)
    client._trusted_paths.add("/org/bluez/hci0/dev_C0_FF_EE_C0_FF_EE")
    phases: list[str] = []
    recovered, new_deadline = await handle_bluez_standby_failure(
        client,
        {
            "ready": False,
            "reason": "services-timeout",
            "dropped_unresolved": 0,
            "info": {"path": "/org/bluez/hci0/dev_C0_FF_EE_C0_FF_EE", "paired": False, "bonded": False},
        },
        prior_drops=0,
        scan_timeout=120.0,
        deadline=0.0,
        phases=phases,
    )
    assert recovered is True
    assert new_deadline > 0.0
    assert removed == [MAC]
    assert started == [True]
    assert phases == ["scan"]
    assert client._trusted_paths == set()
