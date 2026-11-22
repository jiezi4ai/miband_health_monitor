"""Privileged and shell-backed remediation runners for Linux/BlueZ.

All external commands are invoked via argument vectors (never shell=True),
identifiers such as USB VID:PID and adapter names are strictly validated, and
root-required commands only execute automatically when already running as root
or when passwordless sudo (-n) is configured; otherwise they return a copyable
terminal command without ever prompting for or collecting passwords.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from miband_monitor.bluez import is_bluez_platform, list_adapters

from .checks import format_usb_autosuspend_hint, inspect_usb_autosuspend
from .playbooks import PlaybookResult

_HEX4_RE = re.compile(r"^[0-9a-f]{4}$")
_HCI_NAME_RE = re.compile(r"^hci[0-9]{1,2}$")
_EVENTS_RE = re.compile(r"events:\s*(\d+)", re.IGNORECASE)
_COMMANDS_RE = re.compile(r"commands:\s*(\d+)", re.IGNORECASE)


def _run_subprocess_sync(argv: list[str], timeout: float = 12.0) -> tuple[int, str, str]:
    """Execute an argument vector safely without shell interpolation."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"Command not found: {argv[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"Command timed out after {timeout:.0f}s: {' '.join(argv)}"
    except OSError as exc:
        return 1, "", str(exc)


async def run_command_async(argv: list[str], timeout: float = 12.0) -> tuple[int, str, str]:
    """Run a subprocess in a worker thread to keep the asyncio loop responsive."""
    return await asyncio.to_thread(_run_subprocess_sync, argv, timeout)


async def _privileged_prefix() -> Optional[list[str]]:
    """Return [] if root, ['sudo', '-n'] if passwordless sudo works, else None."""
    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None and geteuid() == 0:
        return []
    if shutil.which("sudo") is None:
        return None
    rc, _out, _err = await run_command_async(["sudo", "-n", "true"], timeout=3.0)
    return ["sudo", "-n"] if rc == 0 else None


async def sample_hci_counters(adapter: str = "hci0") -> Optional[dict[str, int]]:
    """Read hciconfig RX events and TX commands counters when available."""
    if not is_bluez_platform() or not _HCI_NAME_RE.match(adapter):
        return None
    if shutil.which("hciconfig") is None:
        return None
    rc, out, _err = await run_command_async(["hciconfig", adapter], timeout=3.0)
    if rc != 0 or not out:
        return None
    ev_match = _EVENTS_RE.search(out)
    cmd_match = _COMMANDS_RE.search(out)
    if not ev_match or not cmd_match:
        return None
    return {"events": int(ev_match.group(1)), "commands": int(cmd_match.group(1))}


async def run_power_on_adapter() -> PlaybookResult:
    """Turn on the Linux Bluetooth adapter via bluetoothctl."""
    if not is_bluez_platform():
        return PlaybookResult(
            id="power_on_adapter",
            ok=True,
            status="skipped",
            summary="Skipped: adapter power control via BlueZ is Linux-only.",
        )
    if shutil.which("bluetoothctl") is None:
        return PlaybookResult(
            id="power_on_adapter",
            ok=False,
            status="failed",
            summary="bluetoothctl binary was not found on PATH.",
            manual_command="sudo systemctl start bluetooth && bluetoothctl power on",
        )
    rc, out, err = await run_command_async(["bluetoothctl", "power", "on"], timeout=8.0)
    adapters = await list_adapters()
    powered = bool(adapters and adapters[0].get("powered"))
    details = [line for line in (out, err) if line]
    if rc == 0 and powered:
        return PlaybookResult(
            id="power_on_adapter",
            ok=True,
            status="ok",
            summary="Bluetooth adapter is powered on.",
            details=details,
        )
    return PlaybookResult(
        id="power_on_adapter",
        ok=False,
        status="failed",
        summary="Could not power on the Bluetooth adapter.",
        details=details or ["Ensure bluetooth.service is active and rfkill is unblocked."],
        manual_command="sudo rfkill unblock bluetooth && bluetoothctl power on",
    )


async def run_disable_usb_autosuspend() -> PlaybookResult:
    """Set USB power/control=on for the Bluetooth adapter or provide manual steps."""
    if not is_bluez_platform():
        return PlaybookResult(
            id="disable_usb_autosuspend",
            ok=True,
            status="skipped",
            summary="Skipped: USB sysfs autosuspend check is Linux-only.",
        )
    adapters = await list_adapters()
    adapter_name = adapters[0]["name"] if adapters else "hci0"
    usb_power = inspect_usb_autosuspend(adapter_name)
    if usb_power is None:
        return PlaybookResult(
            id="disable_usb_autosuspend",
            ok=True,
            status="skipped",
            summary=f"No USB sysfs power node found for {adapter_name}.",
        )
    if not usb_power.get("risky"):
        return PlaybookResult(
            id="disable_usb_autosuspend",
            ok=True,
            status="ok",
            summary=(
                f"USB autosuspend is already safe ({usb_power['usb_device']}: "
                f"control={usb_power['control']})."
            ),
            data=usb_power,
        )

    control_file = Path(usb_power["power_dir"]) / "control"
    # The manual command is a copyable Linux shell snippet: build it from the
    # reported sysfs string so a Windows/macOS GUI host still renders forward
    # slashes instead of a pathlib-converted local separator.
    manual_cmd = f"echo on | sudo tee {usb_power['power_dir']}/control"
    hint = format_usb_autosuspend_hint(usb_power)
    prefix = await _privileged_prefix()
    if prefix is None:
        return PlaybookResult(
            id="disable_usb_autosuspend",
            ok=False,
            status="needs_privilege",
            summary=(
                f"USB adapter {usb_power['usb_device']} has autosuspend={usb_power['control']}; "
                "root privilege is required to disable it."
            ),
            details=[hint],
            manual_command=manual_cmd,
            data=usb_power,
        )

    if prefix:
        rc, _out, err = await run_command_async(
            [
                *prefix,
                "python3",
                "-c",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('on\\n')",
                str(control_file),
            ],
            timeout=5.0,
        )
    else:
        try:
            control_file.write_text("on\n", encoding="utf-8")
            rc, err = 0, ""
        except OSError as exc:
            rc, err = 1, str(exc)

    refreshed = inspect_usb_autosuspend(adapter_name) or usb_power
    if rc == 0 and not refreshed.get("risky"):
        return PlaybookResult(
            id="disable_usb_autosuspend",
            ok=True,
            status="ok",
            summary=f"Disabled USB autosuspend on {usb_power['usb_device']} (control=on).",
            details=[hint],
            data=refreshed,
        )
    return PlaybookResult(
        id="disable_usb_autosuspend",
        ok=False,
        status="failed",
        summary="Failed to update USB power/control automatically.",
        details=[err] if err else [hint],
        manual_command=manual_cmd,
        data=refreshed,
    )


async def run_usb_reset_adapter() -> PlaybookResult:
    """Reset a wedged USB Bluetooth adapter and restart bluetoothd."""
    if not is_bluez_platform():
        return PlaybookResult(
            id="usb_reset_adapter",
            ok=True,
            status="skipped",
            summary="Skipped: USB Bluetooth reset is Linux-only.",
        )
    adapters = await list_adapters()
    adapter_name = adapters[0]["name"] if adapters else "hci0"
    usb_power = inspect_usb_autosuspend(adapter_name)
    vid = (usb_power or {}).get("vendor_id") or ""
    pid = (usb_power or {}).get("product_id") or ""
    if not (_HEX4_RE.match(vid) and _HEX4_RE.match(pid)):
        manual_cmd = "lsusb && sudo usbreset <vid:pid> && sudo systemctl restart bluetooth"
        return PlaybookResult(
            id="usb_reset_adapter",
            ok=False,
            status="needs_privilege",
            summary="Could not detect USB VID:PID automatically; run lsusb and usbreset manually.",
            details=["D-Bus Powered=false/true does not recover wedged BARROT radios; USB reset is required."],
            manual_command=manual_cmd,
        )

    usb_id = f"{vid}:{pid}"
    manual_cmd = f"sudo usbreset {usb_id} && sudo systemctl restart bluetooth"
    prefix = await _privileged_prefix()
    if prefix is None or shutil.which("usbreset") is None:
        reason = (
            "usbreset command not installed (install usbutils) or no passwordless sudo."
            if shutil.which("usbreset") is None
            else "Root privilege is required to reset USB hardware and restart bluetoothd."
        )
        return PlaybookResult(
            id="usb_reset_adapter",
            ok=False,
            status="needs_privilege",
            summary=f"Detected USB adapter {usb_id}; run the command below in a terminal.",
            details=[reason, "After running it, retry Connect or run the 15s RF probe."],
            manual_command=manual_cmd,
            data={"vendor_id": vid, "product_id": pid},
        )

    rc1, out1, err1 = await run_command_async([*prefix, "usbreset", usb_id], timeout=10.0)
    await asyncio.sleep(0.5)
    rc2, out2, err2 = await run_command_async(
        [*prefix, "systemctl", "restart", "bluetooth"], timeout=12.0
    )
    details = [line for line in (out1, err1, out2, err2) if line]
    if rc1 == 0 and rc2 == 0:
        return PlaybookResult(
            id="usb_reset_adapter",
            ok=True,
            status="ok",
            summary=f"USB adapter {usb_id} reset and bluetooth service restarted.",
            details=details,
            recommended_next=["probe_radio_scan"],
            data={"vendor_id": vid, "product_id": pid},
        )
    return PlaybookResult(
        id="usb_reset_adapter",
        ok=False,
        status="failed",
        summary=f"Automatic USB reset for {usb_id} returned an error.",
        details=details,
        manual_command=manual_cmd,
        data={"vendor_id": vid, "product_id": pid},
    )
