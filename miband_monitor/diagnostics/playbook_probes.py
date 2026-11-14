"""Read-only diagnostic playbook runners (doctor check and listen-only RF probe)."""

from __future__ import annotations

import asyncio
import contextlib
import io
from typing import Any, Callable, Optional

from bleak import BleakScanner

from miband_monitor import bluez
from miband_monitor.ble.identity import device_matches, is_placeholder_device_id
from miband_monitor.config.defaults import DEFAULT_DATA_DIR
from miband_monitor.config.privacy import redact_text

from .doctor import run_doctor
from .playbook_privileged import sample_hci_counters
from .playbooks import PlaybookResult, recommend_from_report_lines


async def run_doctor_playbook(
    device_id: str,
    auth_key: str,
    output_dir: str = DEFAULT_DATA_DIR,
) -> PlaybookResult:
    """Run read-only environment self-check and return structured findings."""
    lines: list[str] = []
    stdout_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf):
        exit_code = await run_doctor(device_id, auth_key, output_dir, emit=lines.append)

    extra = [line.strip() for line in stdout_buf.getvalue().splitlines() if line.strip()]
    summary_line = (
        extra[-1] if extra else ("Checks passed" if exit_code == 0 else "Checks found errors")
    )
    recommended = recommend_from_report_lines(lines)
    has_warn = any(line.startswith("[WARN]") for line in lines)
    status = "ok" if exit_code == 0 and not has_warn else ("warn" if exit_code == 0 else "failed")

    return PlaybookResult(
        id="doctor_check",
        ok=(exit_code == 0),
        status=status,
        summary=redact_text(summary_line),
        details=[redact_text(line) for line in lines],
        recommended_next=recommended,
        data={
            "exit_code": exit_code,
            "lines": [redact_text(line) for line in lines],
            "recommended": recommended,
        },
    )


async def run_probe_radio_scan(
    device_id: str,
    *,
    device_name: Optional[str] = None,
    duration: float = 15.0,
    scanner_factory: Optional[Callable[..., Any]] = None,
) -> PlaybookResult:
    """Run a listen-only BLE probe without calling Connect or Disconnect."""
    wait_seconds = max(3.0, min(float(duration), 90.0))
    stats = {"band": 0, "other": 0}
    sample_rssi: list[int] = []
    seen_other: set[str] = set()

    def _on_detection(device: Any, advertisement: Any) -> None:
        if device_id and not is_placeholder_device_id(device_id) and device_matches(
            device_id, device_name, device, advertisement
        ):
            stats["band"] += 1
            rssi = getattr(advertisement, "rssi", None)
            if isinstance(rssi, int):
                sample_rssi.append(rssi)
        else:
            stats["other"] += 1
            addr = str(getattr(device, "address", "") or "")
            if addr:
                seen_other.add(addr)

    before = await sample_hci_counters()
    factory = scanner_factory or BleakScanner
    kwargs = bluez.scanner_kwargs(factory)
    scanner = factory(detection_callback=_on_detection, **kwargs)
    try:
        await scanner.start()
        await asyncio.sleep(wait_seconds)
    except Exception as exc:
        return PlaybookResult(
            id="probe_radio_scan",
            ok=False,
            status="failed",
            summary=f"BLE probe failed to start: {redact_text(str(exc))}",
            recommended_next=["power_on_adapter", "usb_reset_adapter"],
        )
    finally:
        with contextlib.suppress(Exception):
            await scanner.stop()
    after = await sample_hci_counters()

    air_events: Optional[int] = None
    if before is not None and after is not None:
        delta_events = after["events"] - before["events"]
        delta_cmds = after["commands"] - before["commands"]
        air_events = max(0, delta_events - delta_cmds)

    band_cnt = stats["band"]
    other_cnt = stats["other"]
    details = [
        f"Probe window: {wait_seconds:.0f}s (listen-only, zero Connect calls)",
        f"Band pulses matched: {band_cnt}"
        + (f" (RSSI {min(sample_rssi)}..{max(sample_rssi)} dBm)" if sample_rssi else ""),
        f"Other BLE packets: {other_cnt} ({len(seen_other)} unique devices)",
    ]
    if air_events is not None:
        details.append(f"HCI air_events (delta_events - delta_commands): {air_events}")

    if band_cnt == 0 and other_cnt == 0:
        return PlaybookResult(
            id="probe_radio_scan",
            ok=False,
            status="failed",
            summary="0 BLE packets received from ANY device; USB adapter radio may be wedged (-112).",
            details=details,
            recommended_next=["usb_reset_adapter", "power_on_adapter"],
            data={"band_packets": band_cnt, "other_packets": other_cnt, "air_events": air_events},
        )
    if band_cnt == 0:
        details.append(
            "Adapter radio is healthy (other BLE devices seen). A Mi Band 6 emits one pulse every "
            "40-60s when idle; verify phone Bluetooth is OFF and Zepp Life public broadcast is enabled."
        )
        return PlaybookResult(
            id="probe_radio_scan",
            ok=True,
            status="warn",
            summary=f"Radio healthy ({other_cnt} other BLE packets), no band pulse within {wait_seconds:.0f}s.",
            details=details,
            data={"band_packets": band_cnt, "other_packets": other_cnt, "air_events": air_events},
        )
    return PlaybookResult(
        id="probe_radio_scan",
        ok=True,
        status="ok",
        summary=f"Radio healthy: captured {band_cnt} Mi Band advertising pulse(s) and {other_cnt} other packets.",
        details=details,
        data={"band_packets": band_cnt, "other_packets": other_cnt, "air_events": air_events},
    )
