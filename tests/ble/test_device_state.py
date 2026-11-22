"""B-4: device state machine + busy semantics on the shared event channel."""

from __future__ import annotations

from miband_monitor.ble import DEVICE_EVENT, DeviceState, DeviceStateMachine


def test_state_transitions_emit_events():
    events: list[tuple] = []
    fsm = DeviceStateMachine(publish=lambda kind, payload: events.append((kind, payload)))

    assert fsm.state == DeviceState.NOT_CONNECTED
    assert fsm.transition(DeviceState.CONNECTING)
    assert fsm.transition(DeviceState.CONNECTED)
    assert fsm.transition(DeviceState.INITIALIZING)
    assert fsm.transition(DeviceState.INITIALIZED)
    assert not fsm.transition(DeviceState.INITIALIZED)  # no-op

    assert fsm.state == DeviceState.INITIALIZED
    assert fsm.transitions == 4
    assert all(kind == DEVICE_EVENT for kind, _ in events)
    assert [p["state"] for _, p in events] == [
        "connecting", "connected", "initializing", "initialized",
    ]
    assert events[0][1]["transition_from"] == "not_connected"
    assert not events[0][1]["unexpected"]


def test_unexpected_jump_is_flagged():
    events: list[dict] = []
    fsm = DeviceStateMachine(publish=lambda _kind, payload: events.append(payload))
    fsm.transition(DeviceState.CONNECTING)
    fsm.transition(DeviceState.CONNECTED)
    # Jump straight to INITIALIZED (skipping INITIALIZING) is legal-ish but flagged.
    fsm.transition(DeviceState.INITIALIZED)
    assert events[-1]["unexpected"] is True


def test_busy_task_semantics():
    events: list[dict] = []
    fsm = DeviceStateMachine(publish=lambda _kind, payload: events.append(payload))
    assert not fsm.is_busy
    fsm.set_busy("fetch activity data")
    assert fsm.is_busy
    assert fsm.busy_task == "fetch activity data"
    fsm.set_busy("fetch activity data")  # idempotent, no new event
    assert len(events) == 1
    fsm.clear_busy()
    assert not fsm.is_busy
    assert events[-1]["busy_task"] is None
    assert events[-1]["busy_changed"] is True


def test_reconnect_and_reset():
    events: list[dict] = []
    fsm = DeviceStateMachine(publish=lambda _kind, payload: events.append(payload))
    fsm.transition(DeviceState.CONNECTING)
    fsm.note_reconnect()
    assert fsm.reconnect_count == 1
    assert events[-1]["reconnect"] is True
    fsm.transition(DeviceState.CONNECTED)
    fsm.reset()
    assert fsm.state == DeviceState.NOT_CONNECTED
    assert fsm.busy_task is None
    assert fsm.reconnect_count == 0
    assert events[-1]["reset"] is True


def test_timestamp_is_forwarded():
    events: list[tuple] = []
    fsm = DeviceStateMachine(
        publish=lambda kind, payload, ts: events.append((kind, payload, ts)), timestamp=1000.0
    )
    fsm.transition(DeviceState.CONNECTING)
    assert events[0][2] == 1000.0


def test_silent_without_publisher():
    fsm = DeviceStateMachine()
    fsm.transition(DeviceState.CONNECTING)
    fsm.set_busy("x")
    assert fsm.as_dict()["state"] == "connecting"
    assert fsm.as_dict()["is_busy"] is True


def test_client_exposes_state_machine():
    from miband_monitor.ble import MiBand6Client
    from miband_monitor.config.demo import DEMO_AUTH_KEY_HEX, DEMO_DEVICE_ID

    client = MiBand6Client(DEMO_DEVICE_ID, DEMO_AUTH_KEY_HEX)
    assert isinstance(client.device_state, DeviceStateMachine)
    events: list = []
    client.attach_event_publisher(lambda kind, payload: events.append((kind, payload)))
    client.set_device_state(DeviceState.CONNECTING)
    assert events and events[0][0] == DEVICE_EVENT
