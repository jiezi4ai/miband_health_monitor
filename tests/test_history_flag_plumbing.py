"""Guard the runner -> ``_sync_band_history`` -> ``sync_history`` flag plumbing.

Every history flag is threaded through three layers by keyword, so a mismatch
only surfaces when the band is reachable and the whole session then fails with
``TypeError: ... unexpected keyword argument``. That actually happened while
wiring ``--sync-stress``; this test makes the failure immediate and offline.
"""

import pytest

from miband_monitor.ble import StreamCallbacks
from miband_monitor.ble.device_state import DeviceStateMachine
from miband_monitor.cli import runner as cli_runner
from miband_monitor.history.models import HistorySyncResult


class _StubClient:
    """Only what ``_sync_band_history`` touches: the busy flag."""

    def __init__(self):
        self.device_state = DeviceStateMachine()


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    async def fake_sync_history(client, **kwargs):
        seen.update(kwargs)
        return HistorySyncResult()

    monkeypatch.setattr(cli_runner, "sync_history", fake_sync_history)
    return seen


async def test_every_history_flag_reaches_sync_history(captured):
    await cli_runner._sync_band_history(
        _StubClient(),
        7,
        StreamCallbacks(),
        include_spo2_sleep=True,
        include_sports=True,
        include_stress=True,
    )
    assert captured["include_spo2_sleep"] is True
    assert captured["include_sports"] is True
    assert captured["include_stress"] is True
    assert captured["days"] == 7


async def test_flags_default_to_off(captured):
    """A plain history sync must not start fetching the opt-in streams."""
    await cli_runner._sync_band_history(_StubClient(), 1, StreamCallbacks())
    assert captured["include_spo2_sleep"] is False
    assert captured["include_sports"] is False
    assert captured["include_stress"] is False
