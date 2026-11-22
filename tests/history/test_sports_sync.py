"""B-12: 0x05 summaries are fetched one per round and advance the cursor."""

from __future__ import annotations

import pytest

from miband_monitor.history import FetchDataType
from miband_monitor.history.fetch_session import parse_with
import miband_monitor.history.sync as sync_module
from tests.history.summary_fixture import SUMMARY_V519_RUNNING, shifted_summary

FIRST = bytes.fromhex(SUMMARY_V519_RUNNING)


def test_dispatcher_routes_sports_summaries_to_the_new_parser():
    samples = parse_with(FetchDataType.SPORTS_SUMMARIES, FIRST, 0.0)
    assert len(samples) == 1
    assert samples[0]["steps"] == 4351 and samples[0]["kind_name"] == "outdoor_running"


async def _run_sync(monkeypatch, replies):
    calls = []

    async def fake_fetch(fetcher, data_type, since, on_progress=None):
        calls.append((data_type, since))
        return replies.pop(0) if replies else (b"", 0.0)

    monkeypatch.setattr(sync_module, "fetch_with_recovery", fake_fetch)
    received = []
    result = await sync_module.sync_history(
        None,
        since_ts=1782000000.0,  # before the fixture's 2026-06-30 start
        include_spo2=False,
        include_activity=False,
        include_sports=True,
        max_rounds=5,
        on_sports=received.append,
    )
    return result, received, calls


async def test_two_summaries_are_fetched_and_the_cursor_advances(monkeypatch):
    replies = [
        (FIRST, 1782879293.0),
        (shifted_summary(3600), 1782882893.0),
        (b"", 0.0),
    ]
    result, received, calls = await _run_sync(monkeypatch, replies)

    assert len(result.sports) == 2 and len(received) == 2
    assert result.rounds["sports"] == 2
    assert all(call[0] == FetchDataType.SPORTS_SUMMARIES for call in calls)
    # The next request starts one second after the first summary's END time
    # (the band, like Gadgetbridge, selects by end time).
    assert calls[1][1].timestamp() == pytest.approx(1782880895.0, abs=1)


async def test_repeated_summary_stops_without_an_infinite_loop(monkeypatch):
    replies = [(FIRST, 1782879293.0), (FIRST, 1782879293.0)]
    result, _received, calls = await _run_sync(monkeypatch, replies)

    assert len(result.sports) == 1
    assert result.rounds["sports"] == 1
    assert len(calls) == 2  # second round was requested, then no-progress break


async def test_summary_parse_failure_is_isolated(monkeypatch):
    replies = [(b"\x07\x02not-a-summary", 1782879293.0)]
    result, _received, _calls = await _run_sync(monkeypatch, replies)

    assert result.sports == []
    assert result.errors and "parse failed" in result.errors[0]
