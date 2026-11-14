"""Tests for activity_history timestamp deduplication and Linux USB autosuspend check."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from miband_monitor.diagnostics import doctor
from miband_monitor.diagnostics.checks import inspect_usb_autosuspend
from miband_monitor.storage import TelemetryStore, read_jsonl
from tests.support import KEY, MAC


def test_activity_history_dedup_across_sqlite_and_jsonl_reopen(tmp_path: Path) -> None:
    sample = {
        "kind": 1,
        "intensity": 30,
        "steps": 45,
        "heart_rate": 132,
        "unknown1": 0,
        "sleep": 0,
        "deep_sleep": 0,
        "rem_sleep": 0,
    }
    sample2 = {**sample, "steps": 50, "heart_rate": 138}

    with TelemetryStore(tmp_path, backend="both") as store:
        store.record_activity_history(sample, timestamp=1700000100.0)
        store.record_activity_history(sample, timestamp=1700000100.0)  # intra-batch dup
        store.record_activity_history(sample2, timestamp=1700000160.0)

    # Reopen against the same output directory and resend an overlapping minute.
    with TelemetryStore(tmp_path, backend="both") as store2:
        store2.record_activity_history(sample, timestamp=1700000100.0)
        store2.record_activity_history(sample, timestamp=1700000220.0)
        db_path = store2.db_path

    jsonl_rows = read_jsonl(tmp_path / "activity_history.jsonl")
    assert [row["ts"] for row in jsonl_rows] == [1700000100.0, 1700000160.0, 1700000220.0]

    conn = sqlite3.connect(db_path)
    try:
        db_ts = [
            row[0]
            for row in conn.execute("SELECT ts FROM activity_history ORDER BY ts").fetchall()
        ]
        assert db_ts == [1700000100.0, 1700000160.0, 1700000220.0]
    finally:
        conn.close()


def _make_fake_sysfs(tmp_path: Path, *, control: str, delay_ms: str) -> Path:
    usb_dev = tmp_path / "devices" / "pci0000" / "usb6" / "6-4"
    bt_iface = usb_dev / "6-4:1.0"
    (usb_dev / "power").mkdir(parents=True)
    bt_iface.mkdir(parents=True)
    (usb_dev / "idVendor").write_text("0x33fa\n", encoding="utf-8")
    (usb_dev / "power" / "control").write_text(f"{control}\n", encoding="utf-8")
    (usb_dev / "power" / "autosuspend_delay_ms").write_text(f"{delay_ms}\n", encoding="utf-8")

    sys_bt = tmp_path / "class" / "bluetooth"
    (sys_bt / "hci0").mkdir(parents=True)
    (sys_bt / "hci0" / "device").symlink_to(bt_iface)
    return sys_bt


def test_inspect_usb_autosuspend_detects_risky_and_safe_nodes(tmp_path: Path) -> None:
    sys_bt_risky = _make_fake_sysfs(tmp_path / "risky", control="auto", delay_ms="2000")
    info_risky = inspect_usb_autosuspend("hci0", sysfs_bluetooth_root=sys_bt_risky)
    assert info_risky is not None
    assert info_risky["usb_device"] == "6-4"
    assert info_risky["risky"] is True

    sys_bt_safe = _make_fake_sysfs(tmp_path / "safe", control="on", delay_ms="2000")
    info_safe = inspect_usb_autosuspend("hci0", sysfs_bluetooth_root=sys_bt_safe)
    assert info_safe is not None
    assert info_safe["risky"] is False

    sys_bt_neg = _make_fake_sysfs(tmp_path / "neg", control="auto", delay_ms="-1")
    info_neg = inspect_usb_autosuspend("hci0", sysfs_bluetooth_root=sys_bt_neg)
    assert info_neg is not None
    assert info_neg["risky"] is False


@pytest.mark.asyncio
async def test_doctor_emits_usb_autosuspend_warning(monkeypatch, tmp_path: Path) -> None:
    sys_bt = _make_fake_sysfs(tmp_path / "sys", control="auto", delay_ms="2000")
    monkeypatch.setattr(doctor, "is_bluez_platform", lambda: True)

    async def mock_adapters(*_a, **_k):
        return [{"name": "hci0", "powered": True, "pairable": False, "discovering": False}]

    async def mock_find(*_a, **_k):
        return None

    orig_inspect = inspect_usb_autosuspend
    monkeypatch.setattr(doctor, "list_adapters", mock_adapters)
    monkeypatch.setattr(doctor, "find_device", mock_find)
    monkeypatch.setattr(
        doctor,
        "inspect_usb_autosuspend",
        lambda name="hci0": orig_inspect(name, sysfs_bluetooth_root=sys_bt),
    )

    lines: list[str] = []
    code = await doctor.run_doctor(MAC, KEY, str(tmp_path / "out"), emit=lines.append)
    text = "\n".join(lines)
    assert code == 0
    assert "usb autosuspend (6-4)" in text
    assert "autosuspend_delay_ms=2000" in text
