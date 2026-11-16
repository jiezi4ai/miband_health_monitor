#!/usr/bin/env python3
"""Explicitly reset the Linux USB Bluetooth adapter, restart BlueZ, and run --doctor.

This is an operator recovery tool (never invoked automatically by the client).
Resetting the USB adapter and restarting ``bluetooth.service`` requires ``sudo``
and briefly disconnects all other Bluetooth peripherals on the host.

Usage::

    .venv/bin/python tools/reset_bt_adapter.py
    .venv/bin/python tools/reset_bt_adapter.py --yes
    .venv/bin/python tools/reset_bt_adapter.py --dry-run
    .venv/bin/python tools/reset_bt_adapter.py --adapter hci0 --vid-pid 33fa:0012
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
SYS_BLUETOOTH = Path("/sys/class/bluetooth")
_VID_PID_RE = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$")


def detect_usb_vid_pid(
    adapter: str = "hci0",
    *,
    sysfs_root: Path = SYS_BLUETOOTH,
) -> Optional[str]:
    """Walk sysfs parents of ``adapter`` to locate USB ``vid:pid``, or return None."""
    device_link = sysfs_root / adapter / "device"
    if not device_link.exists():
        return None
    current = device_link.resolve()
    for candidate in (current, *current.parents):
        vid_file = candidate / "idVendor"
        pid_file = candidate / "idProduct"
        if vid_file.is_file() and pid_file.is_file():
            vid = vid_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
            pid = pid_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
            if len(vid) == 4 and len(pid) == 4:
                return f"{vid}:{pid}"
        if candidate == Path("/sys") or candidate == Path("/"):
            break
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reset a stalled Linux USB Bluetooth adapter, restart bluetooth.service, "
            "and verify readiness with `miband_client.py --doctor`."
        )
    )
    parser.add_argument(
        "--adapter",
        default="hci0",
        help="BlueZ HCI adapter name to inspect in sysfs (default: hci0)",
    )
    parser.add_argument(
        "--vid-pid",
        default=None,
        help="Explicit USB vendor:product ID (e.g. 33fa:0012); auto-detected if omitted",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the interactive confirmation prompt",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the detected adapter and commands without executing them",
    )
    parser.add_argument(
        "--skip-doctor",
        action="store_true",
        help="Do not run `miband_client.py --doctor` after restarting Bluetooth",
    )
    return parser


def _confirm_reset(commands: list[list[str]]) -> bool:
    print("The following privileged commands will briefly disconnect all Bluetooth devices:")
    for cmd in commands:
        print(f"  {' '.join(cmd)}")
    try:
        answer = input("Proceed? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _build_commands(vid_pid: Optional[str]) -> list[list[str]]:
    commands: list[list[str]] = []
    if vid_pid is not None:
        commands.append(["sudo", "usbreset", vid_pid])
    commands.append(["sudo", "systemctl", "restart", "bluetooth"])
    return commands


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if sys.platform != "linux":
        print("Error: tools/reset_bt_adapter.py only supports Linux/BlueZ.", file=sys.stderr)
        return 2

    vid_pid = args.vid_pid
    if vid_pid is not None:
        if not _VID_PID_RE.match(vid_pid):
            print(f"Error: invalid --vid-pid {vid_pid!r}; expected xxxx:xxxx.", file=sys.stderr)
            return 2
        vid_pid = vid_pid.lower()
    else:
        vid_pid = detect_usb_vid_pid(args.adapter)

    if vid_pid is None:
        print(
            f"Note: no USB idVendor/idProduct found for {args.adapter}; "
            "skipping usbreset and restarting bluetooth.service only."
        )
    else:
        print(f"Detected USB Bluetooth adapter for {args.adapter}: {vid_pid}")
        if not args.dry_run and shutil.which("usbreset") is None:
            print("Error: `usbreset` command not found in PATH.", file=sys.stderr)
            return 1

    commands = _build_commands(vid_pid)
    doctor_cmd = [sys.executable, str(ROOT / "miband_client.py"), "--doctor"]

    if args.dry_run:
        print("Dry run (no changes made):")
        for cmd in commands:
            print(f"  {' '.join(cmd)}")
        if not args.skip_doctor:
            print(f"  {' '.join(doctor_cmd)}")
        return 0

    if not args.yes and not _confirm_reset(commands):
        print("Aborted.")
        return 1

    for cmd in commands:
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            print(
                f"Error: command exited with {result.returncode}: {' '.join(cmd)}",
                file=sys.stderr,
            )
            return result.returncode

    if args.skip_doctor:
        return 0

    time.sleep(1.0)
    print(f"Running readiness check: {os.path.basename(sys.executable)} miband_client.py --doctor")
    doctor_res = subprocess.run(doctor_cmd, cwd=str(ROOT), check=False)
    return doctor_res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
