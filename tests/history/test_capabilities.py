"""B-1: capability gate whitelist and sync-time skipping of known-empty types."""

from __future__ import annotations

from miband_monitor.history import (
    CAPABILITIES,
    FetchDataType,
    is_known_empty,
    is_skippable,
)
from miband_monitor.history.capabilities import CapabilityStatus, FetchCapability
from sim_band import SimulatedBand
from tests.support import AUTH_KEY_BYTES, connect_simulated_client as _connected_client


def test_capability_table_covers_every_known_type():
    for data_type in FetchDataType:
        assert data_type in CAPABILITIES, f"no capability record for {data_type.name}"
        cap = CAPABILITIES[data_type]
        assert isinstance(cap, FetchCapability)
        assert cap.data_type is data_type
        assert cap.probed_on == "2026-11-20"


def test_known_empty_types():
    assert is_known_empty(FetchDataType.STATISTICS)
    assert is_known_empty(FetchDataType.SLEEP_SESSION)
    assert not is_known_empty(FetchDataType.ACTIVITY)
    assert not is_known_empty(FetchDataType.SPORTS_SUMMARIES)


def test_skippable_covers_empty_and_needs_id():
    assert is_skippable(FetchDataType.STATISTICS)
    assert is_skippable(FetchDataType.SLEEP_SESSION)
    assert is_skippable(FetchDataType.SPORTS_DETAILS)
    assert not is_skippable(FetchDataType.ACTIVITY)
    assert not is_skippable(FetchDataType.SPORTS_SUMMARIES)


def test_probed_types_never_rely_on_gadgetbridge_matrix():
    """Every status carries a real probe date, not a GB capability-matrix guess."""
    assert CAPABILITIES[FetchDataType.STATISTICS].status == CapabilityStatus.EMPTY
    # Stage-0 probe reversed the doc's "unconfirmed" assumption for 0x05; the
    # stage-4 fetch then confirmed v519 parsing on our own Band 6.
    assert CAPABILITIES[FetchDataType.SPORTS_SUMMARIES].status == CapabilityStatus.AVAILABLE


async def test_sync_skips_a_type_marked_skippable_by_the_gate(monkeypatch):
    """The gate is consulted in sync: a skippable type is never fetched.

    STATISTICS/SLEEP_SESSION are not in the default candidate list, so to prove
    the wiring (not just the table) we temporarily mark ACTIVITY as skippable
    and assert its fetch never runs, while SpO2 still does.
    """
    from miband_monitor.history import sync as sync_module

    real_is_skippable = sync_module.is_skippable
    monkeypatch.setattr(
        sync_module,
        "is_skippable",
        lambda dt: dt == FetchDataType.ACTIVITY or real_is_skippable(dt),
    )

    requested: list[int] = []

    async def recording_fetch(self, data_type, since, *, session=None):
        requested.append(int(data_type))
        return await _real_fetch(self, data_type, since, session=session)

    _real_fetch = sync_module.BandHistoryFetcher.fetch_payload
    monkeypatch.setattr(sync_module.BandHistoryFetcher, "fetch_payload", recording_fetch)

    band = SimulatedBand(auth_key=AUTH_KEY_BYTES)
    client = await _connected_client(band)
    try:
        from miband_monitor.history import sync_history

        await sync_history(client, days=1, timeout=3.0, max_rounds=1)
        assert FetchDataType.ACTIVITY not in requested
        assert FetchDataType.SPO2_NORMAL in requested
    finally:
        await client.disconnect()
