"""Small pure helpers used by individual doctor checks.

Nothing here touches the band: they only read the installed bleak version, the
permissions of the local .env file and format identifiers for display.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:  # Python 3.8+
    from importlib.metadata import PackageNotFoundError, version as _pkg_version
except Exception:  # pragma: no cover - very old Python
    _pkg_version = None  # type: ignore[assignment]

    class PackageNotFoundError(Exception):  # type: ignore[no-redef]
        pass


def _bleak_version() -> str:
    if _pkg_version is None:
        return "unknown"
    try:
        return _pkg_version("bleak")
    except PackageNotFoundError:
        return "not installed"
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def _env_mode_hint() -> Optional[str]:
    """Warn when .env is readable by other local users."""
    if os.name == "nt":
        return None
    env_path = _env_path()
    if not env_path.exists():
        return None
    try:
        mode = env_path.stat().st_mode & 0o777
    except OSError:
        return None
    if mode & 0o077:
        return f"chmod 600 {env_path.name}"
    return None


def _env_path() -> Path:
    """Project-local .env shown by the permission check."""
    from miband_monitor.config.paths import default_env_path

    return default_env_path()


def _mask(identifier: str) -> str:
    """Show only the last two octets of a MAC / last 4 chars of a UUID."""
    text = identifier.strip()
    if ":" in text and len(text) == 17:
        return "XX:XX:XX:XX:" + text[-5:]
    return text[-4:].rjust(len(text), "*") if text else ""


def inspect_usb_autosuspend(
    adapter_name: str = "hci0",
    *,
    sysfs_bluetooth_root: Path = Path("/sys/class/bluetooth"),
) -> Optional[dict]:
    """Read-only inspect of USB Bluetooth adapter autosuspend settings on Linux."""
    dev_link = sysfs_bluetooth_root / adapter_name / "device"
    if not dev_link.exists():
        return None
    try:
        resolved = dev_link.resolve()
    except OSError:
        return None

    usb_node: Optional[Path] = None
    for candidate in (resolved, *resolved.parents):
        if candidate == Path("/"):
            break
        if (candidate / "power").is_dir() and (
            (candidate / "idVendor").exists() or "usb" in candidate.name.lower()
        ):
            usb_node = candidate
            break

    if usb_node is None:
        return None

    power_dir = usb_node / "power"
    try:
        control = (power_dir / "control").read_text(encoding="utf-8").strip()
    except OSError:
        control = "unknown"
    try:
        delay_ms = (power_dir / "autosuspend_delay_ms").read_text(encoding="utf-8").strip()
    except OSError:
        delay_ms = "unknown"

    risky = False
    if control == "auto":
        try:
            risky = int(delay_ms) >= 0
        except ValueError:
            risky = True

    return {
        "usb_device": usb_node.name,
        "control": control,
        "delay_ms": delay_ms,
        "risky": risky,
        "power_dir": str(power_dir),
    }
