"""Band 6 fetch-type capability gates (B-1).

This is the structured, dated form of Gadgetbridge's ``supports*()`` device
coordinator pattern. Each status comes from a recorded **real-device probe** on
a Mi Band 6 (stage-0 gate record: docs/validation/gadgetbridge-gate0.zh-CN.md),
never from Gadgetbridge's capability matrix alone. ``sync_history`` consults
:func:`is_skippable` so a type the hardware already answered "accepted, zero
records" for is not re-probed on every run.

Kept in its own module so the wire-codec module (``protocol.py``) stays under
the 300-line budget and so capability facts have one obvious home to update
when a future probe changes them.
"""

from __future__ import annotations

from .protocol import FetchDataType


class CapabilityStatus:
    """String constants for :attr:`FetchCapability.status`."""

    AVAILABLE = "available"    # probed with data, parser exists and is used
    PENDING = "pending"        # probed with data, no parser yet (future work)
    EMPTY = "empty"            # probe accepted but declared 0 records
    NEEDS_ID = "needs_id"      # cannot be requested standalone (needs an id)


class FetchCapability:
    """One device-capability gate fact: what a real Band 6 answered, and when."""

    __slots__ = ("data_type", "name", "status", "probed_on", "note")

    def __init__(
        self,
        data_type: FetchDataType,
        name: str,
        status: str,
        probed_on: str,
        note: str,
    ) -> None:
        self.data_type = data_type
        self.name = name
        self.status = status
        self.probed_on = probed_on
        self.note = note

    @property
    def is_known_empty(self) -> bool:
        return self.status == CapabilityStatus.EMPTY

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"FetchCapability({self.data_type.name}, status={self.status!r}, "
            f"probed_on={self.probed_on!r})"
        )


#: Band 6 verified-capability whitelist. ``sync_history`` skips EMPTY and
#: NEEDS_ID types; AVAILABLE/PENDING types remain requestable.
CAPABILITIES: dict[FetchDataType, FetchCapability] = {
    FetchDataType.ACTIVITY: FetchCapability(
        FetchDataType.ACTIVITY, "activity", CapabilityStatus.AVAILABLE, "2026-11-20",
        "5531 minute records; parser used by sync_history.",
    ),
    FetchDataType.SPORTS_SUMMARIES: FetchCapability(
        FetchDataType.SPORTS_SUMMARIES, "sports_summaries", CapabilityStatus.AVAILABLE,
        "2026-11-20", "v519 summary captured on our Band 6 (treadmill, 493 steps); "
        "parser used by sync_history when --sync-sports is enabled.",
    ),
    FetchDataType.SPORTS_DETAILS: FetchCapability(
        FetchDataType.SPORTS_DETAILS, "sports_details", CapabilityStatus.NEEDS_ID,
        "2026-11-20", "status 0x02 without a summary id; not standalone.",
    ),
    FetchDataType.SPO2_NORMAL: FetchCapability(
        FetchDataType.SPO2_NORMAL, "spo2", CapabilityStatus.AVAILABLE, "2026-11-20",
        "Verified on hardware; parser used by sync_history.",
    ),
    FetchDataType.SPO2_SLEEP: FetchCapability(
        FetchDataType.SPO2_SLEEP, "spo2_sleep", CapabilityStatus.AVAILABLE, "2026-11-20",
        "30-byte layout verified; opt-in stream with its own table.",
    ),
    FetchDataType.STATISTICS: FetchCapability(
        FetchDataType.STATISTICS, "statistics", CapabilityStatus.EMPTY, "2026-11-20",
        "Accepted, 0 records; B-13 suspended until a probe reports data.",
    ),
    FetchDataType.PAI: FetchCapability(
        FetchDataType.PAI, "pai", CapabilityStatus.AVAILABLE, "2026-11-20",
        "Accepted, one 102-byte snapshot record that mirrors the app's PAI state "
        "(it advanced 11-10 -> 11-17 only after a Zepp sync, so it lags and is not "
        "the current value). Matches five Zepp numbers exactly.",
    ),
    FetchDataType.STRESS_MANUAL: FetchCapability(
        FetchDataType.STRESS_MANUAL, "stress_manual", CapabilityStatus.EMPTY,
        "2026-11-20", "Accepted, 0 records: no manual stress measurement was ever taken.",
    ),
    FetchDataType.STRESS_AUTOMATIC: FetchCapability(
        FetchDataType.STRESS_AUTOMATIC, "stress_automatic", CapabilityStatus.AVAILABLE,
        "2026-11-20",
        "Accepted, 5761 minutes of one-byte-per-minute data (11-13 10:58 -> 11-17 10:58). "
        "Parser handles 0xFF and 0xFE as sentinels; scale confirmed against two Zepp days "
        "(max/min/bands exact, mean floor). Wired into sync_history via --sync-stress (schema v3).",
    ),
    FetchDataType.SLEEP_SESSION: FetchCapability(
        FetchDataType.SLEEP_SESSION, "sleep_session", CapabilityStatus.EMPTY,
        "2026-11-20", "Accepted, 0 records; Band 6 has no firmware sleep stages.",
    ),
}


def is_known_empty(data_type: FetchDataType) -> bool:
    """True when a real device already answered this type with 0 records.

    Unknown types default to *not* empty so a new fetch type is never silently
    blocked before it has been probed.
    """
    capability = CAPABILITIES.get(data_type)
    return capability.is_known_empty if capability is not None else False


def is_skippable(data_type: FetchDataType) -> bool:
    """True when sync should not request this type at all (empty or needs an id)."""
    capability = CAPABILITIES.get(data_type)
    if capability is None:
        return False
    return capability.status in (CapabilityStatus.EMPTY, CapabilityStatus.NEEDS_ID)
