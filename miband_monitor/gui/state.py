"""GUI connection wizard state machine and live telemetry status."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
import time
from typing import Any, Deque, Optional

STEP_ORDER: tuple[str, ...] = (
    "preflight",
    "discovering",
    "resolving_gatt",
    "authenticating",
    "streaming",
)


@dataclass
class GuiState:
    """Observable state of the GUI session and 5-step BLE connection wizard."""

    phase: str = "idle"  # idle | preflight | discovering | resolving_gatt | authenticating | streaming | reconnecting | error
    running: bool = False
    connected: bool = False
    mode: str = "idle"  # idle | real | demo
    status_message: str = "Ready to connect."
    last_error: Optional[str] = None
    attempt: int = 0
    scan_elapsed_s: int = 0
    band_packets: int = 0
    other_packets: int = 0
    pulse_detected: bool = False
    history_syncing: bool = False
    imu_enabled: bool = False
    workout_enabled: bool = False
    arm_pairing_agent: bool = False
    recommended_playbooks: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    last_doctor: Optional[dict[str, Any]] = None
    last_playbook: Optional[dict[str, Any]] = None
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self._logs: Deque[dict[str, Any]] = deque(maxlen=150)

    def append_log(self, level: str, logger_name: str, message: str, ts: Optional[float] = None) -> dict[str, Any]:
        entry = {
            "ts": round(ts or time.time(), 3),
            "level": level,
            "logger": logger_name,
            "message": message,
        }
        self._logs.append(entry)
        self.updated_at = time.time()
        return entry

    def add_recommendations(self, playbook_ids: list[str]) -> None:
        for pid in playbook_ids:
            if pid not in self.recommended_playbooks:
                self.recommended_playbooks.append(pid)

    def clear_recommendations(self) -> None:
        self.recommended_playbooks.clear()

    def reset_for_session(self, *, mode: str, options: dict[str, Any]) -> None:
        self.phase = "preflight"
        self.running = True
        self.connected = False
        self.mode = mode
        self.status_message = "Preparing BLE session..."
        self.last_error = None
        self.attempt = 1
        self.scan_elapsed_s = 0
        self.band_packets = 0
        self.other_packets = 0
        self.pulse_detected = False
        self.history_syncing = False
        self.imu_enabled = bool(options.get("imu"))
        self.workout_enabled = bool(options.get("workout"))
        self.options = dict(options)
        self.recommended_playbooks.clear()
        self.updated_at = time.time()

    def mark_stopped(self, *, error: Optional[str] = None) -> None:
        self.running = False
        self.connected = False
        self.history_syncing = False
        if error:
            self.phase = "error"
            self.last_error = error
            self.status_message = error
        else:
            self.phase = "idle"
            self.mode = "idle"
            self.status_message = "Session stopped."
        self.updated_at = time.time()

    def steps_snapshot(self) -> list[dict[str, str]]:
        """Return step statuses ('pending' | 'active' | 'done' | 'error') for UI."""
        active_idx = STEP_ORDER.index(self.phase) if self.phase in STEP_ORDER else -1
        if self.phase == "reconnecting":
            active_idx = 1
        steps: list[dict[str, str]] = []
        for idx, step_id in enumerate(STEP_ORDER):
            if self.phase == "idle":
                state = "pending"
            elif self.phase == "error":
                state = "error" if idx == max(0, active_idx) else "pending"
            elif self.phase == "streaming":
                state = "done" if idx < len(STEP_ORDER) - 1 else "active"
            elif idx < active_idx:
                state = "done"
            elif idx == active_idx:
                state = "active"
            else:
                state = "pending"
            steps.append({"id": step_id, "state": state})
        return steps

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = self.steps_snapshot()
        payload["logs"] = list(self._logs)[-80:]
        return payload
