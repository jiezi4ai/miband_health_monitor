"""B-6: FetchSession progress, bounded recovery and parser plug-in."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from miband_monitor.history import (
    FetchDataType,
    FetchProgress,
    FetchSession,
    HistoryFetchError,
    PARSERS,
    fetch_with_recovery,
    parse_with,
    register_parser,
)
from sim_band import SimulatedBand
from tests.support import AUTH_KEY_BYTES, connect_simulated_client as _connected_client


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------
async def test_fetch_emits_progress_phases():
    band = SimulatedBand(auth_key=AUTH_KEY_BYTES)
    client = await _connected_client(band)
    seen: list[FetchProgress] = []
    try:
        from miband_monitor.history import BandHistoryFetcher

        fetcher = BandHistoryFetcher(client, timeout=3.0)
        session = FetchSession(FetchDataType.ACTIVITY, on_progress=seen.append)
        payload, _ = await fetcher.fetch_payload(
            FetchDataType.ACTIVITY, datetime.now() - timedelta(hours=2), session=session
        )
        assert payload
    finally:
        await client.disconnect()

    phases = [snap.phase for snap in seen]
    assert "metadata" in phases
    assert "complete" in phases
    assert "ack" in phases
    assert seen[0].data_type == int(FetchDataType.ACTIVITY)
    # The session also retains its own snapshots.
    assert session.snapshots == seen


# ---------------------------------------------------------------------------
# Bounded error recovery
# ---------------------------------------------------------------------------
async def test_recovery_retries_transient_error_then_succeeds():
    attempts = {"n": 0}

    class FlakyFetcher:
        async def fetch_payload(self, data_type, since, *, session=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                if session:
                    session.progress("metadata", expected=1)
                raise RuntimeError("org.bluez.Error.InProgress")
            return b"payload", 1000.0

    events: list[FetchProgress] = []
    result = await fetch_with_recovery(
        FlakyFetcher(), FetchDataType.ACTIVITY, datetime.now(),
        on_progress=events.append, initial_backoff=0.001, max_backoff=0.002,
    )
    assert result == (b"payload", 1000.0)
    assert attempts["n"] == 2
    assert any(snap.phase == "error" for snap in events)


async def test_recovery_does_not_retry_non_transient_error():
    attempts = {"n": 0}

    class BadFetcher:
        async def fetch_payload(self, data_type, since, *, session=None):
            attempts["n"] += 1
            raise HistoryFetchError("band rejected fetch type")

    with pytest.raises(HistoryFetchError, match="rejected"):
        await fetch_with_recovery(
            BadFetcher(), FetchDataType.ACTIVITY, datetime.now(),
            initial_backoff=0.001, max_retries=3,
        )
    assert attempts["n"] == 1


async def test_recovery_respects_max_retries():
    attempts = {"n": 0}

    class AlwaysFails:
        async def fetch_payload(self, data_type, since, *, session=None):
            attempts["n"] += 1
            raise RuntimeError("device disconnected")

    with pytest.raises(HistoryFetchError, match="fetch failed"):
        await fetch_with_recovery(
            AlwaysFails(), FetchDataType.ACTIVITY, datetime.now(),
            initial_backoff=0.001, max_backoff=0.002, max_retries=2,
        )
    assert attempts["n"] == 3  # initial + 2 retries


# ---------------------------------------------------------------------------
# Parser plug-in
# ---------------------------------------------------------------------------
def test_parser_registry_override():
    data_type = FetchDataType.SPORTS_SUMMARIES
    previous = PARSERS.get(data_type)

    def fake_parser(payload: bytes, start_ts: float) -> list:
        return [{"raw": payload.hex(), "ts": start_ts}]

    try:
        register_parser(data_type, fake_parser)
        assert PARSERS[data_type] is fake_parser
        parsed = parse_with(data_type, b"\x01\x02", 123.0)
        assert parsed == [{"raw": "0102", "ts": 123.0}]
    finally:
        # 0x05 now has a built-in parser; restore the exact previous state.
        if previous is None:
            PARSERS.pop(data_type, None)
        else:
            PARSERS[data_type] = previous


def test_parse_with_falls_back_to_builtin_dispatch():
    # ACTIVITY has no registered parser; the built-in one handles it.
    parsed = parse_with(FetchDataType.ACTIVITY, b"", 0.0)
    assert parsed == []


def test_session_parse_uses_injected_parser():
    called = {"v": False}

    def parser(payload, start_ts):
        called["v"] = True
        return []

    session = FetchSession(FetchDataType.ACTIVITY, parser=parser)
    session.parse(b"", 0.0)
    assert called["v"]
