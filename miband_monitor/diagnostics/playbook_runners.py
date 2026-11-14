"""Async execution engine for scripted diagnostic and remediation playbooks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from miband_monitor import bluez
from miband_monitor.ble.identity import is_placeholder_device_id
from miband_monitor.config.defaults import DEFAULT_DATA_DIR
from miband_monitor.config.env import secure_env_file
from miband_monitor.config.paths import default_env_path
from miband_monitor.config.privacy import mask_address

from .playbook_privileged import (
    run_disable_usb_autosuspend,
    run_power_on_adapter,
    run_usb_reset_adapter,
)
from .playbook_probes import run_doctor_playbook, run_probe_radio_scan
from .playbooks import PlaybookResult, get_playbook


async def run_clear_ghost_link(device_id: str) -> PlaybookResult:
    """Disconnect a stale Connected=True link in BlueZ if present."""
    if not bluez.is_bluez_platform():
        return PlaybookResult(
            id="clear_ghost_link",
            ok=True,
            status="skipped",
            summary="Skipped: BlueZ ghost-link cleanup is Linux-only.",
        )
    if not device_id or is_placeholder_device_id(device_id):
        return PlaybookResult(
            id="clear_ghost_link",
            ok=False,
            status="failed",
            summary="Configure DEVICE_ID before clearing a BlueZ link.",
        )
    info = await bluez.find_device(device_id)
    if info is None:
        return PlaybookResult(
            id="clear_ghost_link",
            ok=True,
            status="skipped",
            summary=f"Device {mask_address(device_id)} is not cached in BlueZ; nothing to disconnect.",
        )
    if not info.get("connected"):
        return PlaybookResult(
            id="clear_ghost_link",
            ok=True,
            status="ok",
            summary=f"Device {mask_address(device_id)} is already Connected=no.",
        )
    disconnected = await bluez.disconnect_device(device_id)
    if disconnected:
        return PlaybookResult(
            id="clear_ghost_link",
            ok=True,
            status="ok",
            summary=f"Cleared residual Connected=True link for {mask_address(device_id)}.",
        )
    return PlaybookResult(
        id="clear_ghost_link",
        ok=False,
        status="failed",
        summary=f"Failed to disconnect {mask_address(device_id)} via D-Bus.",
        manual_command=f"bluetoothctl disconnect {device_id}",
    )


async def run_trust_and_pairable(device_id: str) -> PlaybookResult:
    """Mark the band Trusted=True and ensure adapter Pairable=True."""
    if not bluez.is_bluez_platform():
        return PlaybookResult(
            id="trust_and_pairable",
            ok=True,
            status="skipped",
            summary="Skipped: BlueZ Trust/Pairable settings are Linux-only.",
        )
    adapters = await bluez.list_adapters()
    adapter_name = adapters[0]["name"] if adapters else "hci0"
    pairable_ok = await bluez.set_adapter_pairable(adapter_name, True)
    details = [f"Adapter {adapter_name} Pairable=True: {'ok' if pairable_ok else 'failed'}"]

    if not device_id or is_placeholder_device_id(device_id):
        return PlaybookResult(
            id="trust_and_pairable",
            ok=pairable_ok,
            status="warn" if pairable_ok else "failed",
            summary="Adapter pairable updated, but DEVICE_ID is not configured yet.",
            details=details,
        )

    info = await bluez.find_device(device_id)
    if info is None or not info.get("path"):
        details.append(
            f"Device {mask_address(device_id)} is not in the BlueZ object tree yet; "
            "it will be trusted automatically once discovered."
        )
        return PlaybookResult(
            id="trust_and_pairable",
            ok=True,
            status="warn",
            summary="Adapter Pairable enabled; device not cached in BlueZ yet.",
            details=details,
        )

    trust_ok = await bluez.set_device_trusted(info["path"], True)
    details.append(f"Device {mask_address(device_id)} Trusted=True: {'ok' if trust_ok else 'failed'}")
    if trust_ok:
        return PlaybookResult(
            id="trust_and_pairable",
            ok=True,
            status="ok",
            summary=f"Marked {mask_address(device_id)} as Trusted=True and adapter Pairable=True.",
            details=details,
        )
    return PlaybookResult(
        id="trust_and_pairable",
        ok=False,
        status="failed",
        summary="Failed to mark device Trusted via D-Bus.",
        details=details,
        manual_command=f"bluetoothctl trust {device_id}",
    )


async def run_reset_stale_bond(device_id: str) -> PlaybookResult:
    """Remove stale BlueZ Device1 bond state and signal next connect to enable Agent1."""
    if not bluez.is_bluez_platform():
        return PlaybookResult(
            id="reset_stale_bond",
            ok=True,
            status="skipped",
            summary="Skipped: BlueZ stale-bond reset is Linux-only.",
        )
    if not device_id or is_placeholder_device_id(device_id):
        return PlaybookResult(
            id="reset_stale_bond",
            ok=False,
            status="failed",
            summary="Configure DEVICE_ID before removing a BlueZ bond.",
        )
    info = await bluez.find_device(device_id)
    if info is None:
        return PlaybookResult(
            id="reset_stale_bond",
            ok=True,
            status="ok",
            summary=f"No cached BlueZ object for {mask_address(device_id)}; pairing agent armed for next connect.",
            data={"arm_pairing_agent": True},
        )
    removed = await bluez.remove_device(device_id)
    if removed:
        return PlaybookResult(
            id="reset_stale_bond",
            ok=True,
            status="ok",
            summary=f"Removed cached BlueZ bond for {mask_address(device_id)} and armed pairing agent.",
            details=["Make sure phone Bluetooth is OFF before clicking Connect."],
            data={"arm_pairing_agent": True},
        )
    return PlaybookResult(
        id="reset_stale_bond",
        ok=False,
        status="failed",
        summary=f"Failed to remove BlueZ device {mask_address(device_id)}.",
        manual_command=f"bluetoothctl remove {device_id}",
    )


async def run_fix_env_permissions(env_path: Optional[Path] = None) -> PlaybookResult:
    """Ensure local .env credentials file has 0600 permissions."""
    if os.name == "nt":
        return PlaybookResult(
            id="fix_env_permissions",
            ok=True,
            status="skipped",
            summary="Skipped: POSIX chmod 0600 does not apply on Windows.",
        )
    if env_path is not None:
        target = Path(env_path)
    else:
        cwd_env = Path(".env")
        target = cwd_env if cwd_env.is_file() else default_env_path()
    if not target.is_file():
        return PlaybookResult(
            id="fix_env_permissions",
            ok=True,
            status="skipped",
            summary=f"No {target.name} file found; nothing to tighten.",
        )
    secure_env_file(target)
    mode = target.stat().st_mode & 0o777
    ok = (mode & 0o077) == 0
    return PlaybookResult(
        id="fix_env_permissions",
        ok=ok,
        status="ok" if ok else "failed",
        summary=f"{target.name} permissions are now {oct(mode)}.",
    )


async def run_playbook(
    playbook_id: str,
    *,
    device_id: str = "",
    auth_key: str = "",
    output_dir: str = DEFAULT_DATA_DIR,
    device_name: Optional[str] = None,
    probe_duration: float = 15.0,
    env_path: Optional[Path] = None,
) -> PlaybookResult:
    """Dispatch a registered playbook by ID."""
    spec = get_playbook(playbook_id)
    if spec is None:
        return PlaybookResult(
            id=playbook_id,
            ok=False,
            status="failed",
            summary=f"Unknown playbook: {playbook_id}",
        )
    if playbook_id == "doctor_check":
        return await run_doctor_playbook(device_id, auth_key, output_dir)
    if playbook_id == "probe_radio_scan":
        return await run_probe_radio_scan(
            device_id, device_name=device_name, duration=probe_duration
        )
    if playbook_id == "clear_ghost_link":
        return await run_clear_ghost_link(device_id)
    if playbook_id == "trust_and_pairable":
        return await run_trust_and_pairable(device_id)
    if playbook_id == "reset_stale_bond":
        return await run_reset_stale_bond(device_id)
    if playbook_id == "power_on_adapter":
        return await run_power_on_adapter()
    if playbook_id == "fix_env_permissions":
        return await run_fix_env_permissions(env_path)
    if playbook_id == "disable_usb_autosuspend":
        return await run_disable_usb_autosuspend()
    if playbook_id == "usb_reset_adapter":
        return await run_usb_reset_adapter()
    return PlaybookResult(
        id=playbook_id,
        ok=False,
        status="failed",
        summary=f"No runner implemented for playbook: {playbook_id}",
    )
