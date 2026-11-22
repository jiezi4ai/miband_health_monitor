"""Device lifecycle state machine + busy task (B-4).

Gadgetbridge's ``GBDevice.State`` (NOT_CONNECTED -> CONNECTING -> CONNECTED ->
INITIALIZING -> INITIALIZED) plus a human-readable busy-task lock is mirrored
here as a small, dependency-free state object. Every transition and busy change
is published through :meth:`TelemetryHub.publish_event` -- the **same event
channel** workout and battery (B-14) use -- so no second event bus is introduced.

Events use kind ``"device"`` with ``state`` / ``busy_task`` / ``reconnect_count``
in the payload; the dashboard's out-of-band event stream already fans these out
without storing them in metric series.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Optional


class DeviceState(str, Enum):
    """Coarse lifecycle states, ordered like GBDevice.State."""

    NOT_CONNECTED = "not_connected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"


#: Legal transitions. A gap (e.g. INITIALIZED -> CONNECTING after a drop) is a
#: normal reconnect, so we allow returning to CONNECTING from any state; the
#: forward chain is otherwise strict.
_ALLOWED: dict[DeviceState, set[DeviceState]] = {
    DeviceState.NOT_CONNECTED: {DeviceState.CONNECTING},
    DeviceState.CONNECTING: {
        DeviceState.CONNECTED,
        DeviceState.NOT_CONNECTED,
        DeviceState.CONNECTING,  # retry within the same connect phase
    },
    DeviceState.CONNECTED: {
        DeviceState.INITIALIZING,
        DeviceState.NOT_CONNECTED,
        DeviceState.CONNECTING,
    },
    DeviceState.INITIALIZING: {
        DeviceState.INITIALIZED,
        DeviceState.NOT_CONNECTED,
        DeviceState.CONNECTING,
    },
    DeviceState.INITIALIZED: {
        DeviceState.NOT_CONNECTED,
        DeviceState.CONNECTING,
    },
}

#: Event kind on the shared hub channel (B-14 battery uses "battery").
DEVICE_EVENT = "device"


class DeviceStateMachine:
    """Track device state, busy task and reconnect count; emit hub events.

    ``publish`` is injected so this object stays independent of the dashboard
    package; callers pass ``hub.publish_event``. Passing None makes it silent.
    """

    def __init__(
        self,
        publish: Optional[Callable[[str, dict], None]] = None,
        *,
        timestamp: Optional[float] = None,
    ) -> None:
        self._publish = publish
        self._timestamp = timestamp
        self.state = DeviceState.NOT_CONNECTED
        self.busy_task: Optional[str] = None
        self.reconnect_count = 0
        self.transitions = 0

    def _emit(self, **payload: Any) -> None:
        if self._publish is None:
            return
        full = {
            "state": self.state.value,
            "busy_task": self.busy_task,
            "reconnect_count": self.reconnect_count,
            **payload,
        }
        if self._timestamp is not None:
            self._publish(DEVICE_EVENT, full, self._timestamp)
        else:
            self._publish(DEVICE_EVENT, full)

    def transition(self, state: DeviceState) -> bool:
        """Move to *state* if legal. Returns True when the state changed."""
        state = DeviceState(state)
        if state == self.state:
            return False
        # Unexpected jumps (e.g. a drop straight back to CONNECTING) are allowed
        # and stamped `unexpected` in the event so dashboards can see the path.
        previous = self.state.value
        unexpected = state not in _ALLOWED.get(self.state, set())
        self.state = state
        self.transitions += 1
        self._emit(transition_from=previous, unexpected=unexpected)
        return True

    def set_busy(self, task: Optional[str]) -> None:
        """Set/clear a human-readable busy task (GB's setBusyTask)."""
        if task == self.busy_task:
            return
        self.busy_task = task
        self._emit(busy_changed=True)

    def clear_busy(self) -> None:
        self.set_busy(None)

    @property
    def is_busy(self) -> bool:
        return self.busy_task is not None

    def note_reconnect(self) -> None:
        """Increment the reconnect counter (event carries the new value)."""
        self.reconnect_count += 1
        self._emit(reconnect=True)

    def reset(self) -> None:
        """Return to NOT_CONNECTED with counters cleared (session teardown)."""
        self.state = DeviceState.NOT_CONNECTED
        self.busy_task = None
        self.reconnect_count = 0
        self._emit(reset=True)

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "busy_task": self.busy_task,
            "reconnect_count": self.reconnect_count,
            "is_busy": self.is_busy,
            "transitions": self.transitions,
        }
