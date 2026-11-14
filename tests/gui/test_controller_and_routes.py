"""Integration tests for GUI controller, state machine, config masking and HTTP routes."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

from miband_monitor.dashboard import DashboardServer, TelemetryHub
from miband_monitor.gui import GuiSessionController, get_masked_config, update_gui_config
from miband_monitor.gui.log_bridge import GuiLogBridge
from miband_monitor.gui.state import GuiState


async def _http_req(port: int, method: str, path: str, body: dict | None = None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        raw_body = b""
        headers = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1", "Connection: close"]
        if body is not None:
            raw_body = json.dumps(body).encode("utf-8")
            headers.append("Content-Type: application/json")
            headers.append(f"Content-Length: {len(raw_body)}")
        payload = ("\r\n".join(headers) + "\r\n\r\n").encode("latin-1") + raw_body
        writer.write(payload)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(), timeout=5.0)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass

    head, _, resp_body = data.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n")[0].split(b" ")[1])
    return status, json.loads(resp_body.decode("utf-8"))


def test_config_manager_masks_secrets_and_writes_0600(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.delenv("DEVICE_ID", raising=False)
    monkeypatch.delenv("DEVICE_MAC", raising=False)
    monkeypatch.delenv("AUTH_KEY", raising=False)

    cfg = update_gui_config(
        {
            "device_id": "C0:FF:EE:C0:FF:EE",
            "auth_key": "69c4e0d86a7b0430d8cdb78070b4c55a",
            "band_tz": "Asia/Shanghai",
        },
        env_path=env_file,
    )
    assert cfg["device_id_configured"] is True
    assert cfg["device_id_masked"] == "C0:FF:**:**:FF:EE"
    assert cfg["auth_key_configured"] is True
    assert cfg["auth_key_valid"] is True
    assert "69c4e0d8" not in json.dumps(cfg)

    masked = get_masked_config(env_path=env_file)
    assert masked["band_tz"] == "Asia/Shanghai"
    assert "auth_key" not in masked


def test_log_bridge_drives_5_step_state_and_redacts_secrets():
    state = GuiState()
    state.reset_for_session(mode="real", options={"imu": False})
    bridge = GuiLogBridge(state)

    def _emit(level: int, msg: str) -> None:
        rec = logging.LogRecord("MiBand6Client", level, __file__, 1, msg, (), None)
        bridge.emit(rec)

    _emit(logging.INFO, "Waiting for the band's next broadcast pulse at C0:FF:EE:C0:FF:EE...")
    assert state.phase == "discovering"
    _emit(logging.INFO, "Scanning for band... (15s elapsed, band=0 packets, other BLE=4)")
    assert state.scan_elapsed_s == 15
    assert state.other_packets == 4
    _emit(logging.INFO, "Band pulse detected (C0:FF:EE:C0:FF:EE); arming BLE link...")
    assert state.phase == "resolving_gatt"
    _emit(logging.INFO, "Initiating chunked ECDH handshake (sending client public key)...")
    assert state.phase == "authenticating"
    _emit(logging.INFO, "Streaming session 1 started (duration=until Ctrl+C, imu=False).")
    assert state.phase == "streaming"
    assert state.connected is True
    _emit(logging.WARNING, "BlueZ link dropped: dropped-unresolved-after-5.1s key=69c4e0d86a7b0430d8cdb78070b4c55a")
    assert "reset_stale_bond" in state.recommended_playbooks
    logs_joined = "\n".join(item["message"] for item in state.to_dict()["logs"])
    assert "69c4e0d86a7b0430d8cdb78070b4c55a" not in logs_joined
    assert "C0:FF:EE:C0:FF:EE" not in logs_joined


async def test_gui_routes_demo_session_scan_and_export(tmp_path, monkeypatch):
    monkeypatch.setattr("miband_monitor.diagnostics.doctor.is_bluez_platform", lambda: False)
    env_file = tmp_path / ".env"
    out_dir = tmp_path / "data"

    class _FakeScanner:
        @staticmethod
        async def discover(timeout=12.0, return_adv=True, **_kwargs):
            return {
                "other": (
                    SimpleNamespace(address="AA:BB:CC:00:00:01", name="Speaker"),
                    SimpleNamespace(rssi=-75, local_name="Speaker"),
                ),
                "band": (
                    SimpleNamespace(address="C0:FF:EE:C0:FF:EE", name="Mi Smart Band 6"),
                    SimpleNamespace(rssi=-52, local_name="Mi Smart Band 6"),
                ),
            }

    hub = TelemetryHub()
    hub.attach_loop(asyncio.get_running_loop())
    controller = GuiSessionController(
        hub,
        output_dir=str(out_dir),
        storage_backend="sqlite",
        env_path=env_file,
        scanner_factory=_FakeScanner,
    )
    server = DashboardServer(hub, host="127.0.0.1", port=0, controller=controller)
    await server.start()
    try:
        # 1. Initial state and doctor
        st, body = await _http_req(server.port, "GET", "/api/gui/state")
        assert st == 200
        assert body["phase"] == "idle"
        assert len(body["playbooks"]) >= 9

        st, doc = await _http_req(server.port, "GET", "/api/gui/doctor")
        assert st == 200 and doc["id"] == "doctor_check"

        # 2. Scan and save config
        st, scan = await _http_req(server.port, "POST", "/api/gui/scan", {"duration": 3})
        assert st == 200
        assert scan["devices"][0]["address"] == "C0:FF:EE:C0:FF:EE"
        assert scan["devices"][0]["is_band"] is True

        st, cfg_resp = await _http_req(
            server.port,
            "POST",
            "/api/gui/config",
            {"device_id": "C0:FF:EE:C0:FF:EE", "auth_key": "0123456789abcdef0123456789abcdef"},
        )
        assert st == 200 and cfg_resp["ok"] is True
        assert cfg_resp["config"]["device_id_masked"] == "C0:FF:**:**:FF:EE"

        # 3. Start simulated demo session and verify live telemetry reaches hub
        st, start_resp = await _http_req(
            server.port,
            "POST",
            "/api/gui/connect",
            {"demo": True, "imu": True, "workout": True},
        )
        assert st == 200 and start_resp["running"] is True

        for _ in range(40):
            _st, snap = await _http_req(server.port, "GET", "/api/snapshot")
            if snap["counts"].get("heart_rate", 0) >= 1 and snap["counts"].get("steps", 0) >= 1:
                break
            await asyncio.sleep(0.1)
        assert snap["counts"]["heart_rate"] >= 1
        assert snap["counts"]["steps"] >= 1
        assert snap["gui"]["phase"] == "streaming"

        # 4. Disconnect and export CSV
        st, stop_resp = await _http_req(server.port, "POST", "/api/gui/disconnect", {})
        assert st == 200 and stop_resp["running"] is False

        st, csv_resp = await _http_req(server.port, "POST", "/api/gui/export-csv", {})
        assert st == 200 and csv_resp["ok"] is True
        assert "heart_rate" in csv_resp["tables"]
        assert Path(csv_resp["tables"]["heart_rate"]["path"]).is_file()
    finally:
        await controller.stop_session()
        controller.close()
        await server.stop()


async def test_legacy_server_without_controller_returns_501():
    hub = TelemetryHub()
    server = DashboardServer(hub, host="127.0.0.1", port=0)
    await server.start()
    try:
        st, body = await _http_req(server.port, "GET", "/api/gui/state")
        assert st == 501
        assert "not enabled" in body["error"]
    finally:
        await server.stop()
