"""Unit tests for tools/reset_bt_adapter.py."""

from __future__ import annotations

import builtins
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import reset_bt_adapter


def test_detect_usb_vid_pid_walks_sysfs_parents(tmp_path: Path) -> None:
    usb_dev = tmp_path / "devices" / "pci0" / "usb1" / "1-4"
    bt_iface = usb_dev / "1-4:1.0" / "bluetooth" / "hci0"
    bt_iface.mkdir(parents=True)
    (usb_dev / "idVendor").write_text("33fa\n", encoding="utf-8")
    (usb_dev / "idProduct").write_text("0012\n", encoding="utf-8")

    sysfs_bt = tmp_path / "sys_class_bluetooth"
    hci_dir = sysfs_bt / "hci0"
    hci_dir.mkdir(parents=True)
    (hci_dir / "device").symlink_to(bt_iface)

    assert reset_bt_adapter.detect_usb_vid_pid("hci0", sysfs_root=sysfs_bt) == "33fa:0012"
    assert reset_bt_adapter.detect_usb_vid_pid("hci9", sysfs_root=sysfs_bt) is None


def test_detect_usb_vid_pid_returns_none_for_non_usb_device(tmp_path: Path) -> None:
    pci_dev = tmp_path / "devices" / "pci0" / "uart0"
    pci_dev.mkdir(parents=True)
    sysfs_bt = tmp_path / "sys_class_bluetooth"
    hci_dir = sysfs_bt / "hci0"
    hci_dir.mkdir(parents=True)
    (hci_dir / "device").symlink_to(pci_dev)

    assert reset_bt_adapter.detect_usb_vid_pid("hci0", sysfs_root=sysfs_bt) is None


def test_dry_run_prints_commands_without_running_subprocess(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(reset_bt_adapter, "detect_usb_vid_pid", lambda _a: "33fa:0012")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("must not run subprocess")),
    )

    rc = reset_bt_adapter.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "sudo usbreset 33fa:0012" in out
    assert "sudo systemctl restart bluetooth" in out
    assert "miband_client.py --doctor" in out


def test_yes_executes_usbreset_restart_and_doctor_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(reset_bt_adapter, "detect_usb_vid_pid", lambda _a: "33fa:0012")
    monkeypatch.setattr(reset_bt_adapter.shutil, "which", lambda _cmd: "/usr/bin/usbreset")
    monkeypatch.setattr(reset_bt_adapter.time, "sleep", lambda _s: None)

    ran: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw):
        ran.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = reset_bt_adapter.main(["--yes"])
    assert rc == 0
    assert ran[0] == ["sudo", "usbreset", "33fa:0012"]
    assert ran[1] == ["sudo", "systemctl", "restart", "bluetooth"]
    assert ran[2][1].endswith("miband_client.py")
    assert ran[2][2] == "--doctor"


def test_confirmation_abort_and_non_linux_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert reset_bt_adapter.main([]) == 2

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(reset_bt_adapter, "detect_usb_vid_pid", lambda _a: None)
    monkeypatch.setattr(builtins, "input", lambda _p="": "n")
    assert reset_bt_adapter.main([]) == 1
