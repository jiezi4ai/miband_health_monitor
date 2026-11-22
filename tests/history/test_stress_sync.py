"""0x13 wiring: the sync loop fetches stress, parses it and reports samples."""

from __future__ import annotations

import pytest

from miband_monitor.history import FetchDataType
from miband_monitor.history.fetch_session import parse_with
import miband_monitor.history.sync as sync_module

BASE = 1_787_000_000.0
#: 0x29=41 mild, four gaps, 0x28=40 mild, ... one byte per minute.
PAYLOAD = bytes.fromhex("29 fe fe fe fe 28 fe fe fe fe ff 2f")


def test_dispatcher_routes_stress_to_the_new_parser():
    samples = parse_with(FetchDataType.STRESS_AUTOMATIC, PAYLOAD, BASE)
    assert [sample["stress"] for sample in samples] == [41, 40, 47]
    assert [sample["band"] for sample in samples] == ["mild"] * 3


async def _run_sync(monkeypatch, replies):
    calls = []

    async def fake_fetch(fetcher, data_type, since, on_progress=None):
        calls.append((data_type, since))
        return replies.pop(0) if replies else (b"", 0.0)

    monkeypatch.setattr(sync_module, "fetch_with_recovery", fake_fetch)
    received = []
    result = await sync_module.sync_history(
        None,
        since_ts=BASE,
        include_spo2=False,
        include_activity=False,
        include_stress=True,
        max_rounds=5,
        on_stress=received.append,
    )
    return result, received, calls


async def test_stress_round_reports_every_measured_minute(monkeypatch):
    result, received, calls = await _run_sync(monkeypatch, [(PAYLOAD, BASE), (b"", 0.0)])

    assert len(result.stress) == 3 and len(received) == 3
    assert result.rounds["stress"] == 1
    assert all(call[0] == FetchDataType.STRESS_AUTOMATIC for call in calls)


async def test_stress_is_not_fetched_unless_asked_for(monkeypatch):
    calls = []

    async def fake_fetch(fetcher, data_type, since, on_progress=None):
        calls.append(data_type)
        return b"", 0.0

    monkeypatch.setattr(sync_module, "fetch_with_recovery", fake_fetch)
    result = await sync_module.sync_history(
        None, since_ts=BASE, include_spo2=False, include_activity=False, max_rounds=1
    )

    assert result.stress == []
    assert FetchDataType.STRESS_AUTOMATIC not in calls


def test_summary_mentions_the_stress_count():
    from miband_monitor.history.models import HistorySyncResult

    result = HistorySyncResult()
    result.stress = [{"ts": BASE, "stress": 40, "band": "mild"}]
    result.rounds["stress"] = 1
    assert "1 stress reading(s)" in sync_module.summarize_history_result(result)
