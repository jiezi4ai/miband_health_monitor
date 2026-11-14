"""BlueZ MTU negotiation and transient connection-error classifiers."""

from __future__ import annotations

from miband_monitor.bluez import errors, mtu, platform


async def test_try_acquire_mtu_uses_the_backend(monkeypatch):
    monkeypatch.setattr(platform, "is_bluez_platform", lambda: True)

    class Backend:
        mtu_size = 23
        called = False

        def _acquire_mtu(self):
            self.called = True
            self.mtu_size = 247

    class Client:
        def __init__(self):
            self._backend = Backend()

        @property
        def mtu_size(self):
            return self._backend.mtu_size

        async def get_services(self):
            return None

    client = Client()
    assert await mtu.try_acquire_mtu(client) is True
    assert client._backend.called is True
    assert client.mtu_size == 247


async def test_try_acquire_mtu_supports_a_coroutine_backend(monkeypatch):
    """bleak 3.x implements ``_acquire_mtu`` as a coroutine."""
    monkeypatch.setattr(platform, "is_bluez_platform", lambda: True)

    class Backend:
        mtu_size = 23

        async def _acquire_mtu(self):
            self.mtu_size = 185

    class Client:
        def __init__(self):
            self._backend = Backend()

        @property
        def mtu_size(self):
            return self._backend.mtu_size

    client = Client()
    assert await mtu.try_acquire_mtu(client) is True
    assert client.mtu_size == 185


async def test_try_acquire_mtu_is_a_noop_without_a_bluez_backend(monkeypatch):
    monkeypatch.setattr(platform, "is_bluez_platform", lambda: True)
    assert await mtu.try_acquire_mtu(object()) is False


def test_is_transient_connect_error():
    assert errors.is_transient_connect_error(Exception("le-connection-abort-by-local")) is True
    assert errors.is_transient_connect_error(Exception("org.bluez.Error.InProgress")) is True
    assert errors.is_transient_connect_error(Exception("Software caused connection abort")) is True
    assert errors.is_transient_connect_error(Exception("Permanent authentication failure")) is False


def test_is_in_progress_error():
    assert errors.is_in_progress_error(Exception("org.bluez.Error.InProgress")) is True
    assert errors.is_in_progress_error(Exception("GATT InProgress")) is True
    assert errors.is_in_progress_error(Exception("Other error")) is False


async def test_wait_for_bluez_link_grants_services_grace_and_tracks_unresolved_drops(
    monkeypatch,
):
    import asyncio
    import sys
    import types
    from types import SimpleNamespace
    from miband_monitor import bluez

    fake_time = [0.0]
    real_loop = asyncio.get_running_loop()
    real_sleep = asyncio.sleep
    target_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_46_BE"

    class _LoopProxy:
        def time(self) -> float:
            return fake_time[0]

        def __getattr__(self, name: str):
            return getattr(real_loop, name)

    # Sequence: (connected=True, resolved=False) -> drop (False, False) ->
    # reconnect right before deadline (True, False) -> resolve inside 10s grace (True, True)
    states = iter([
        {"path": target_path, "connected": True, "services_resolved": False},
        {"path": target_path, "connected": False, "services_resolved": False},
        {"path": target_path, "connected": True, "services_resolved": False},
        {"path": target_path, "connected": True, "services_resolved": False},
        {"path": target_path, "connected": True, "services_resolved": True},
    ])

    class _FakeManager:
        async def call_get_managed_objects(self) -> dict:
            return {target_path: {}}

    class _FakeProxy:
        def get_interface(self, _iface: str):
            return _FakeManager()

    class _FakeBus:
        async def connect(self):
            return self

        async def introspect(self, *_args):
            return object()

        def get_proxy_object(self, *_args):
            return _FakeProxy()

        async def call(self, _msg) -> None:
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
    monkeypatch.setattr(
        bluez.devices, "_info_for_address", lambda _objs, _addr: next(states)
    )
    monkeypatch.setattr("miband_monitor.bluez.link.asyncio.get_running_loop", _LoopProxy)

    async def fake_sleep(delay: float) -> None:
        fake_time[0] += max(delay, 1.0)
        await real_sleep(0)

    monkeypatch.setattr("miband_monitor.bluez.link.asyncio.sleep", fake_sleep)

    outcome = await bluez.wait_for_bluez_link("C0:FF:EE:C0:FF:EE", timeout=2.5)
    assert outcome["ready"] is True
    assert outcome["reason"] == "resolved"
    assert outcome["dropped_unresolved"] == 1


async def test_disconnect_device_logs_exception_type_on_timeout(monkeypatch, caplog):
    import logging
    import sys
    import types
    from types import SimpleNamespace
    from miband_monitor.bluez import admin, devices, platform

    monkeypatch.setattr(platform, "is_bluez_platform", lambda: True)

    async def fake_find(_addr: str, timeout: float = 2.0):
        return {"connected": True, "path": "/org/bluez/hci0/dev_AA_BB"}

    monkeypatch.setattr(devices, "find_device", fake_find)

    class _TimeoutBus:
        async def connect(self):
            raise TimeoutError()

    fake_dbus_fast = types.ModuleType("dbus_fast")
    fake_dbus_fast.BusType = SimpleNamespace(SYSTEM=1)
    fake_dbus_fast.Message = lambda **kw: SimpleNamespace(**kw)
    fake_dbus_aio = types.ModuleType("dbus_fast.aio")
    fake_dbus_aio.MessageBus = lambda **_kw: _TimeoutBus()

    monkeypatch.setitem(sys.modules, "dbus_fast", fake_dbus_fast)
    monkeypatch.setitem(sys.modules, "dbus_fast.aio", fake_dbus_aio)
    caplog.set_level(logging.DEBUG, logger="MiBand6Client.bluez")

    assert await admin.disconnect_device("C0:FF:EE:C0:FF:EE") is False
    assert any("TimeoutError" in rec.message for rec in caplog.records)
