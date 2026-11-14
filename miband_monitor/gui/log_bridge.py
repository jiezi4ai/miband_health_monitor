"""Logging handler that translates BLE/BlueZ logs into GUI state transitions."""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from ..config.privacy import redact_text
from ..diagnostics.playbooks import recommend_playbooks
from .state import GuiState

_SCAN_HEARTBEAT_RE = re.compile(
    r"Scanning for band\.\.\.\s*\((\d+)s elapsed,\s*band=(\d+) packets,\s*other BLE=(\d+)"
)
_SESSION_NUM_RE = re.compile(r"Session (\d+) failed:|next attempt (\d+)")
_RELEVANT_LOGGERS = (
    "MiBand6Client",
    "MiBandBlueZ",
    "MiBandDashboard",
    "MiBandDoctor",
    "MiBandHistory",
    "MiBandGUI",
)


class GuiLogBridge(logging.Handler):
    """Capture redacted backend logs and drive the 5-step GUI state machine."""

    def __init__(
        self,
        state: GuiState,
        *,
        on_change: Optional[Callable[[dict], None]] = None,
        on_log: Optional[Callable[[dict], None]] = None,
    ) -> None:
        super().__init__(level=logging.INFO)
        self._state = state
        self._on_change = on_change
        self._on_log = on_log
        self._prev_levels: dict[str, int] = {}

    def attach(self) -> None:
        for name in _RELEVANT_LOGGERS:
            log = logging.getLogger(name)
            if self not in log.handlers:
                log.addHandler(self)
            if log.getEffectiveLevel() > logging.INFO:
                self._prev_levels[name] = log.level
                log.setLevel(logging.INFO)

    def detach(self) -> None:
        for name in _RELEVANT_LOGGERS:
            log = logging.getLogger(name)
            if self in log.handlers:
                log.removeHandler(self)
            if name in self._prev_levels:
                log.setLevel(self._prev_levels.pop(name))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            raw_msg = record.getMessage()
        except Exception:
            return
        message = redact_text(raw_msg)
        entry = self._state.append_log(record.levelname, record.name, message, record.created)
        state_changed = self._apply_message(record.levelname, message)
        if self._on_log is not None:
            self._on_log(entry)
        if state_changed and self._on_change is not None:
            self._on_change(self._state.to_dict())

    def _apply_message(self, level: str, message: str) -> bool:
        """Update GuiState from a single log line; return True if state changed."""
        if not self._state.running and level not in ("WARNING", "ERROR"):
            return False

        changed = False
        lower = message.lower()

        hb = _SCAN_HEARTBEAT_RE.search(message)
        if hb:
            self._state.phase = "discovering"
            self._state.scan_elapsed_s = int(hb.group(1))
            self._state.band_packets = int(hb.group(2))
            self._state.other_packets = int(hb.group(3))
            self._state.status_message = (
                f"Scanning ({self._state.scan_elapsed_s}s): "
                f"band={self._state.band_packets}, other BLE={self._state.other_packets}"
            )
            return True

        attempt_match = _SESSION_NUM_RE.search(message)
        if attempt_match:
            num = attempt_match.group(1) or attempt_match.group(2)
            if num:
                self._state.attempt = int(num)
                changed = True

        if "band pulse detected" in lower:
            self._state.pulse_detected = True
            self._state.band_packets = max(1, self._state.band_packets)
            self._state.phase = "resolving_gatt"
            self._state.status_message = "Band pulse captured; establishing BLE link..."
            return True

        if (
            "waiting for the band's next broadcast pulse" in lower
            or "waiting for mi band broadcast" in lower
            or "linux/bluez link mode" in lower
            or "bonded band" in lower
        ):
            self._state.phase = "discovering"
            self._state.status_message = "Waiting for band advertising pulse (40-60s period)..."
            return True

        if (
            "establishing ble link" in lower
            or "bluez link to" in lower and "services are resolved" in lower
            or "ble link established" in lower
            or "negotiated att mtu" in lower
            or "settling" in lower and "gatt" in lower
        ):
            self._state.phase = "resolving_gatt"
            self._state.status_message = "BLE link up; resolving GATT services..."
            return True

        if "initiating chunked ecdh handshake" in lower:
            self._state.phase = "authenticating"
            self._state.status_message = "Running ECDH challenge-response authentication..."
            return True

        if "chunked ecdh authentication succeeded" in lower:
            self._state.phase = "authenticating"
            self._state.status_message = "Authenticated; starting telemetry streams..."
            return True

        if "fetching up to" in lower and "band-side history" in lower:
            self._state.history_syncing = True
            self._state.status_message = "Syncing band-side history (activity/SpO2)..."
            return True

        if "band history sync finished" in lower:
            self._state.history_syncing = False
            return True

        if "streaming session" in lower and "started" in lower:
            self._state.phase = "streaming"
            self._state.connected = True
            self._state.last_error = None
            self._state.clear_recommendations()
            self._state.status_message = "Connected and streaming live telemetry."
            return True

        if "ble link to" in lower and "lost" in lower:
            self._state.connected = False
            if self._state.running:
                self._state.phase = "reconnecting"
                self._state.status_message = "BLE link dropped; preparing fast reconnect..."
                changed = True

        if "reconnecting in" in lower or ("session " in lower and " failed:" in lower):
            self._state.connected = False
            self._state.phase = "reconnecting"
            self._state.status_message = message
            changed = True

        recs = recommend_playbooks(error_text=message)
        if recs:
            self._state.add_recommendations(recs)
            changed = True

        if level == "ERROR":
            self._state.last_error = message
            changed = True

        return changed
