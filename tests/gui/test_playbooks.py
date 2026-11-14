"""Unit tests for scripted diagnostic and remediation playbooks."""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

import pytest

from miband_monitor.diagnostics import (
    list_playbooks,
    recommend_playbooks,
    run_playbook,
)
from miband_monitor.diagnostics import playbook_privileged, playbook_probes, playbook_runners


def test_playbook_catalog_contains_core_remediations():
    ids = {item["id"] for item in list_playbooks()}
    expected = {
        "doctor_check",
        "probe_radio_scan",
        "clear_ghost_link",
        "trust_and_pairable",
        "reset_stale_bond",
        "power_on_adapter",
        "fix_env_permissions",
        "disable_usb_autosuspend",
        "usb_reset_adapter",
    }
    assert expected.issubset(ids)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Adapter received 0 BLE packets (-112 host is down)", "usb_reset_adapter"),
        ("dropped-unresolved-after-5.1s stale LTK", "reset_stale_bond"),
        ("reusing connection Connected=True, ServicesResolved=False", "clear_ghost_link"),
        ("device is NOT bonded; failed to discover services", "trust_and_pairable"),
        ("adapter hci0 powered=no", "power_on_adapter"),
        ("USB autosuspend enabled power/control=auto", "disable_usb_autosuspend"),
        (".env readable by other local users; chmod 600", "fix_env_permissions"),
        ("Could not discover band within 120s", "probe_radio_scan"),
    ],
)
def test_recommend_playbooks_matches_symptoms(text: str, expected: str):
    recs = recommend_playbooks(error_text=text)
    assert expected in recs


async def test_doctor_and_fix_env_permissions_playbooks(tmp_path, monkeypatch):
    monkeypatch.setattr("miband_monitor.diagnostics.doctor.is_bluez_platform", lambda: False)
    env_file = tmp_path / ".env"
    env_file.write_text("DEVICE_ID=C0:FF:EE:C0:FF:EE\nAUTH_KEY=0123456789abcdef0123456789abcdef\n")
    if os.name != "nt":
        env_file.chmod(0o644)

    perm_res = await run_playbook("fix_env_permissions", env_path=env_file)
    assert perm_res.ok
    if os.name != "nt":
        assert (env_file.stat().st_mode & 0o077) == 0

    doc_res = await run_playbook(
        "doctor_check",
        device_id="C0:FF:EE:C0:FF:EE",
        auth_key="0123456789abcdef0123456789abcdef",
        output_dir=str(tmp_path / "out"),
    )
    assert doc_res.ok
    assert doc_res.data["exit_code"] == 0
    assert any("ECDH backend" in line for line in doc_res.details)


async def test_bluez_ble_playbooks_with_mocks(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(playbook_runners.bluez, "is_bluez_platform", lambda: True)

    async def fake_find(addr: str):
        return {
            "path": "/org/bluez/hci0/dev_C0_FF_EE_C0_FF_EE",
            "address": addr,
            "connected": True,
            "trusted": False,
            "paired": True,
        }

    async def fake_disconnect(addr: str) -> bool:
        calls.append(("disconnect", addr))
        return True

    async def fake_list_adapters():
        return [{"name": "hci0", "powered": True}]

    async def fake_pairable(adapter: str, val: bool) -> bool:
        calls.append(("pairable", adapter, val))
        return True

    async def fake_trusted(path: str, val: bool) -> bool:
        calls.append(("trusted", path, val))
        return True

    async def fake_remove(addr: str) -> bool:
        calls.append(("remove", addr))
        return True

    monkeypatch.setattr(playbook_runners.bluez, "find_device", fake_find)
    monkeypatch.setattr(playbook_runners.bluez, "disconnect_device", fake_disconnect)
    monkeypatch.setattr(playbook_runners.bluez, "list_adapters", fake_list_adapters)
    monkeypatch.setattr(playbook_runners.bluez, "set_adapter_pairable", fake_pairable)
    monkeypatch.setattr(playbook_runners.bluez, "set_device_trusted", fake_trusted)
    monkeypatch.setattr(playbook_runners.bluez, "remove_device", fake_remove)

    ghost = await run_playbook("clear_ghost_link", device_id="C0:FF:EE:C0:FF:EE")
    assert ghost.ok and ghost.status == "ok"
    assert ("disconnect", "C0:FF:EE:C0:FF:EE") in calls

    trust = await run_playbook("trust_and_pairable", device_id="C0:FF:EE:C0:FF:EE")
    assert trust.ok and trust.status == "ok"
    assert ("pairable", "hci0", True) in calls
    assert ("trusted", "/org/bluez/hci0/dev_C0_FF_EE_C0_FF_EE", True) in calls

    reset = await run_playbook("reset_stale_bond", device_id="C0:FF:EE:C0:FF:EE")
    assert reset.ok and reset.data["arm_pairing_agent"] is True
    assert ("remove", "C0:FF:EE:C0:FF:EE") in calls


async def test_probe_radio_scan_classifies_deaf_vs_healthy(monkeypatch):
    monkeypatch.setattr(playbook_probes, "sample_hci_counters", lambda: _coro(None))
    monkeypatch.setattr("miband_monitor.diagnostics.playbook_probes.asyncio.sleep", lambda _s: _coro(None))

    def _make_scanner(events):
        class _FakeScanner:
            def __init__(self, detection_callback=None, **_kwargs):
                self._cb = detection_callback

            async def start(self):
                for dev, adv in events:
                    self._cb(dev, adv)

            async def stop(self):
                return None

        return _FakeScanner

    deaf = await playbook_probes.run_probe_radio_scan(
        "C0:FF:EE:C0:FF:EE", scanner_factory=_make_scanner([])
    )
    assert not deaf.ok
    assert "usb_reset_adapter" in deaf.recommended_next

    other_only = await playbook_probes.run_probe_radio_scan(
        "C0:FF:EE:C0:FF:EE",
        scanner_factory=_make_scanner(
            [(SimpleNamespace(address="AA:BB:CC:11:22:33", name="Other"), SimpleNamespace(rssi=-70, local_name="Other"))]
        ),
    )
    assert other_only.ok and other_only.status == "warn"

    band_seen = await playbook_probes.run_probe_radio_scan(
        "C0:FF:EE:C0:FF:EE",
        scanner_factory=_make_scanner(
            [(SimpleNamespace(address="C0:FF:EE:C0:FF:EE", name="Mi Smart Band 6"), SimpleNamespace(rssi=-54, local_name="Mi Smart Band 6"))]
        ),
    )
    assert band_seen.ok and band_seen.status == "ok"
    assert band_seen.data["band_packets"] == 1


async def test_privileged_playbooks_return_copyable_commands_without_sudo(monkeypatch):
    monkeypatch.setattr(playbook_privileged, "is_bluez_platform", lambda: True)
    monkeypatch.setattr(playbook_privileged, "list_adapters", lambda: _coro([{"name": "hci0", "powered": True}]))
    monkeypatch.setattr(
        playbook_privileged,
        "inspect_usb_autosuspend",
        lambda _adapter: {
            "adapter": "hci0",
            "usb_device": "6-4",
            "control": "auto",
            "delay_ms": "2000",
            "risky": True,
            "power_dir": "/sys/bus/usb/devices/6-4/power",
            "vendor_id": "33fa",
            "product_id": "0012",
        },
    )
    monkeypatch.setattr(playbook_privileged, "_privileged_prefix", lambda: _coro(None))

    auto_res = await run_playbook("disable_usb_autosuspend")
    assert auto_res.status == "needs_privilege"
    assert "/sys/bus/usb/devices/6-4/power/control" in (auto_res.manual_command or "")

    reset_res = await run_playbook("usb_reset_adapter")
    assert reset_res.status == "needs_privilege"
    assert "33fa:0012" in (reset_res.manual_command or "")


def test_remediate_cli_list_json(capsys):
    from tools.remediate import main as remediate_main

    code = remediate_main(["--list", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(item["id"] == "probe_radio_scan" for item in payload)


async def _coro(value):
    return value
