"""Tests for USB autosuspend startup preflight and clean SIGTERM shutdown."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import pytest

import miband_monitor.cli.app as cli_app
from miband_monitor.diagnostics.checks import (
    format_usb_autosuspend_hint,
    inspect_usb_autosuspend,
    warn_usb_autosuspend_preflight,
)
from miband_monitor.storage import read_jsonl
from tests.support import KEY, MAC


def _make_usb_bt_sysfs(
    tmp_path: Path,
    *,
    control: str,
    delay_ms: str,
    vendor_id: str = "0x33fa",
    product_id: str = "0012",
) -> Path:
    usb_dev = tmp_path / "devices" / "pci0000" / "usb1" / "1-1"
    bt_iface = usb_dev / "1-1:1.0"
    (usb_dev / "power").mkdir(parents=True)
    bt_iface.mkdir(parents=True)
    (usb_dev / "idVendor").write_text(f"{vendor_id}\n", encoding="utf-8")
    (usb_dev / "idProduct").write_text(f"{product_id}\n", encoding="utf-8")
    (usb_dev / "power" / "control").write_text(f"{control}\n", encoding="utf-8")
    (usb_dev / "power" / "autosuspend_delay_ms").write_text(f"{delay_ms}\n", encoding="utf-8")

    sys_bt = tmp_path / "class" / "bluetooth"
    (sys_bt / "hci0").mkdir(parents=True)
    (sys_bt / "hci0" / "device").symlink_to(bt_iface)
    return sys_bt


def test_usb_autosuspend_preflight_logs_udev_hint_only_when_risky(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    risky_sysfs = _make_usb_bt_sysfs(tmp_path / "risky", control="auto", delay_ms="2000")
    info = inspect_usb_autosuspend("hci0", sysfs_bluetooth_root=risky_sysfs)
    assert info is not None
    assert info["vendor_id"] == "33fa"
    assert info["product_id"] == "0012"

    hint = format_usb_autosuspend_hint(info)
    assert "echo on | sudo tee" in hint
    assert 'ACTION=="add|change|bind"' in hint
    assert 'ATTR{idVendor}=="33fa", ATTR{idProduct}=="0012"' in hint
    assert 'DRIVER=="btusb"' in hint
    assert 'ATTR{../power/control}="on"' in hint

    test_logger = logging.getLogger("test.preflight")
    caplog.set_level(logging.WARNING, logger="test.preflight")
    risky = warn_usb_autosuspend_preflight(test_logger, sysfs_bluetooth_root=risky_sysfs)
    assert len(risky) == 1
    assert any("autosuspend enabled" in rec.message for rec in caplog.records)

    caplog.clear()
    safe_sysfs = _make_usb_bt_sysfs(tmp_path / "safe", control="on", delay_ms="2000")
    assert warn_usb_autosuspend_preflight(test_logger, sysfs_bluetooth_root=safe_sysfs) == []
    assert caplog.records == []


async def test_cli_main_runs_preflight_for_real_bluez_not_demo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli_app, "is_bluez_platform", lambda: True)
    monkeypatch.setattr(
        cli_app,
        "warn_usb_autosuspend_preflight",
        lambda _log: (calls.append("preflight"), [])[1],
    )

    code_demo = await cli_app.main(["--demo", "1", "--storage", "none"])
    assert code_demo == 0
    assert calls == []

    async def fake_run_monitor(*_a, **_kw) -> None:
        return None

    monkeypatch.setenv("DEVICE_ID", MAC)
    monkeypatch.setenv("AUTH_KEY", "a" * 32)
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setattr(cli_app, "run_monitor", fake_run_monitor)

    code_live = await cli_app.main(
        ["--device-id", MAC, "--output", str(tmp_path), "--storage", "none"]
    )
    assert code_live == 0
    assert calls == ["preflight"]


@pytest.mark.skipif(sys.platform == "win32" or not hasattr(signal, "SIGTERM"), reason="POSIX SIGTERM only")
async def test_cli_main_handles_sigterm_and_flushes_workout_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "workout_out"
    started = asyncio.Event()
    disconnected = [False]

    async def slow_monitor(*_a, callbacks=None, workout=None, **_kw) -> None:
        assert callbacks is not None and callbacks.heart_rate is not None
        assert workout is not None
        callbacks.heart_rate(138)
        started.set()
        try:
            await asyncio.sleep(30.0)
        finally:
            disconnected[0] = True

    monkeypatch.setenv("DEVICE_ID", MAC)
    monkeypatch.setenv("AUTH_KEY", "a" * 32)
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setattr(cli_app, "is_bluez_platform", lambda: False)
    monkeypatch.setattr(cli_app, "run_monitor", slow_monitor)

    async def _send_sigterm() -> None:
        await asyncio.wait_for(started.wait(), timeout=2.0)
        os.kill(os.getpid(), signal.SIGTERM)

    killer = asyncio.create_task(_send_sigterm())
    try:
        code = await cli_app.main(
            [
                "--device-id",
                MAC,
                "--workout",
                "--storage",
                "both",
                "--output",
                str(out_dir),
                "--export-csv",
            ]
        )
    finally:
        await killer

    assert code == 0
    assert disconnected[0] is True
    assert (out_dir / "workout_summary.json").is_file()
    assert (out_dir / "mi_band.db").is_file()
    assert (out_dir / "csv" / "heart_rate.csv").is_file()
    assert len(read_jsonl(out_dir / "heart_rate.jsonl")) == 1
