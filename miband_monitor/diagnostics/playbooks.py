"""Registry of scripted diagnostic and remediation playbooks.

Each playbook encapsulates one actionable troubleshooting or repair task derived
from hardware validation findings (ghost links, stale BlueZ LTK bonds, USB
adapter radio wedges, autosuspend, permissions, and listen-only RF probes).
Playbooks can be recommended automatically from doctor checks or runtime logs,
and invoked either from the web GUI or via tools/remediate.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional, Sequence


@dataclass(frozen=True)
class PlaybookSpec:
    """Metadata describing a scripted remediation or diagnostic action."""

    id: str
    title: str
    summary: str
    category: str  # "diagnose" | "ble" | "system" | "config"
    requires_root: bool = False
    linux_only: bool = False
    modifies_system: bool = False
    symptoms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlaybookResult:
    """Structured execution outcome returned to both GUI and CLI callers."""

    id: str
    ok: bool
    status: str  # "ok" | "warn" | "failed" | "needs_privilege" | "skipped"
    summary: str
    details: list[str] = field(default_factory=list)
    manual_command: Optional[str] = None
    recommended_next: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PLAYBOOK_CATALOG: tuple[PlaybookSpec, ...] = (
    PlaybookSpec(
        id="doctor_check",
        title="Environment & BlueZ Baseline Check",
        summary="Read-only check of .env permissions, ECDH backend, adapter power, and BlueZ pairing/trust state.",
        category="diagnose",
        symptoms=("baseline", "config", "unknown"),
    ),
    PlaybookSpec(
        id="probe_radio_scan",
        title="Listen-Only RF Probe (15s)",
        summary="Safely listen for BLE advertising pulses without calling Connect/Disconnect to separate silent band vs deaf adapter.",
        category="diagnose",
        symptoms=("timeout", "no_pulse", "deaf", "zero_packets"),
    ),
    PlaybookSpec(
        id="clear_ghost_link",
        title="Clear Residual BlueZ Ghost Link",
        summary="Disconnect a stale Connected=True link before reconnecting (skips safely if not connected).",
        category="ble",
        linux_only=True,
        modifies_system=True,
        symptoms=("ghost", "reusing_connection", "already_connected"),
    ),
    PlaybookSpec(
        id="trust_and_pairable",
        title="Mark Device Trusted & Enable Pairable",
        summary="Set Trusted=True so BlueZ caches GATT handles and auto-reconnects, and ensure adapter Pairable=True.",
        category="ble",
        linux_only=True,
        modifies_system=True,
        symptoms=("not_trusted", "unknown_object", "service_watchdog", "not_bonded"),
    ),
    PlaybookSpec(
        id="reset_stale_bond",
        title="Clear Stale LTK Bond & Arm Pairing Agent",
        summary="Remove mismatched BlueZ bond state (fixes ~5s ServicesResolved=False drops) and arm the pairing agent for next connect.",
        category="ble",
        linux_only=True,
        modifies_system=True,
        symptoms=("stale_ltk", "dropped_unresolved", "auth_canceled"),
    ),
    PlaybookSpec(
        id="power_on_adapter",
        title="Power On Bluetooth Adapter",
        summary="Turn on the Linux Bluetooth adapter radio via bluetoothctl.",
        category="system",
        linux_only=True,
        modifies_system=True,
        symptoms=("adapter_off",),
    ),
    PlaybookSpec(
        id="fix_env_permissions",
        title="Tighten .env Permissions (0600)",
        summary="Restrict local .env credential file permissions to owner read/write only.",
        category="config",
        modifies_system=True,
        symptoms=("env_perms",),
    ),
    PlaybookSpec(
        id="disable_usb_autosuspend",
        title="Disable USB Bluetooth Autosuspend",
        summary="Set USB power/control=on for the Bluetooth adapter (returns copyable sudo command and udev rule if non-root).",
        category="system",
        requires_root=True,
        linux_only=True,
        modifies_system=True,
        symptoms=("autosuspend",),
    ),
    PlaybookSpec(
        id="usb_reset_adapter",
        title="USB Reset Adapter & Restart bluetoothd",
        summary="Recover a wedged USB radio (-112 / EHOSTDOWN / 0 air packets); provides copyable sudo command when unprivileged.",
        category="system",
        requires_root=True,
        linux_only=True,
        modifies_system=True,
        symptoms=("deaf", "ehostdown", "zero_packets"),
    ),
)

_PLAYBOOK_BY_ID: dict[str, PlaybookSpec] = {spec.id: spec for spec in PLAYBOOK_CATALOG}


def list_playbooks() -> list[dict[str, Any]]:
    """Return serializable metadata for every registered playbook."""
    return [spec.to_dict() for spec in PLAYBOOK_CATALOG]


def get_playbook(playbook_id: str) -> Optional[PlaybookSpec]:
    """Look up a playbook spec by ID."""
    return _PLAYBOOK_BY_ID.get(playbook_id)


def recommend_playbooks(
    *,
    messages: Sequence[str] = (),
    error_text: str = "",
    bluez_info: Optional[dict[str, Any]] = None,
    adapter_powered: Optional[bool] = None,
    usb_autosuspend_risky: bool = False,
    env_perms_warn: bool = False,
) -> list[str]:
    """Return ordered playbook IDs matching observed symptoms or diagnostics."""
    combined = "\n".join([*(messages or ()), error_text or ""]).lower()
    ordered: list[str] = []

    def _add(pid: str) -> None:
        if pid in _PLAYBOOK_BY_ID and pid not in ordered:
            ordered.append(pid)

    if adapter_powered is False or "powered=no" in combined or "no bluetooth adapter" in combined:
        _add("power_on_adapter")

    if any(
        token in combined
        for token in (
            "0 ble packet",
            "adapterdeaf",
            "usbreset",
            "-112",
            "host is down",
            "ehostdown",
            "deaf",
        )
    ):
        _add("usb_reset_adapter")
        _add("probe_radio_scan")

    if any(
        token in combined
        for token in (
            "dropped-unresolved",
            "stale ltk",
            "clearing cached bluez bond",
            "authenticationcanceled",
            "0x08",
        )
    ):
        _add("reset_stale_bond")
        _add("clear_ghost_link")

    if any(
        token in combined
        for token in (
            "ghost",
            "reusing connection",
            "already connected",
            "connected=true, servicesresolved=false",
        )
    ) or (
        bluez_info is not None
        and bluez_info.get("connected")
        and not bluez_info.get("services_resolved")
    ):
        _add("clear_ghost_link")

    if any(
        token in combined
        for token in (
            "not trusted",
            "not bonded",
            "unknownobject",
            "failed to discover services",
            "trust",
        )
    ) or (bluez_info is not None and not bluez_info.get("trusted")):
        _add("trust_and_pairable")

    if usb_autosuspend_risky or "autosuspend" in combined:
        _add("disable_usb_autosuspend")

    if env_perms_warn or "chmod 600" in combined or "readable by other local users" in combined:
        _add("fix_env_permissions")

    if any(
        token in combined
        for token in (
            "could not discover band",
            "could not establish a ble link",
            "timeout",
            "timed out",
            "not known to bluez",
        )
    ):
        _add("probe_radio_scan")
        _add("doctor_check")

    return ordered


def recommend_from_report_lines(lines: Iterable[str]) -> list[str]:
    """Convenience wrapper extracting recommendations from formatted doctor lines."""
    return recommend_playbooks(messages=list(lines))
