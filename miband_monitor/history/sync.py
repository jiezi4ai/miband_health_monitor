"""High-level history synchronisation loop and its CLI summary helper.

``sync_history()`` repeats fetches until the band stops making forward progress,
isolating per-data-type failures so one unavailable stream does not abort the
others. Sample persistence is the caller's job: it is delivered through the
``on_spo2`` / ``on_activity`` / ``on_spo2_sleep`` callbacks.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, tzinfo
from typing import Callable, Optional

from miband_monitor.config.defaults import DEFAULT_HISTORY_DAYS

from .capabilities import is_skippable
from .fetch_session import FetchProgress, fetch_with_recovery, parse_with
from .fetcher import BandHistoryFetcher
from .models import HistoryParseError, HistorySyncResult
from .protocol import (
    DEFAULT_MAX_ROUNDS,
    DEFAULT_TIMEOUT,
    FetchDataType,
    _format_ts,
    _timestamp_usable,
    logger,
    resolve_band_tz,
)


# ---------------------------------------------------------------------------
# High-level sync loop
# ---------------------------------------------------------------------------
async def sync_history(
    client,
    *,
    days: int = DEFAULT_HISTORY_DAYS,
    since_ts: Optional[float] = None,
    until_ts: Optional[float] = None,
    include_spo2: bool = True,
    include_activity: bool = True,
    include_spo2_sleep: bool = False,
    include_sports: bool = False,
    include_stress: bool = False,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    timeout: float = DEFAULT_TIMEOUT,
    band_tz: Optional[str | tzinfo] = None,
    on_spo2: Optional[Callable[[dict], None]] = None,
    on_activity: Optional[Callable[[dict], None]] = None,
    on_spo2_sleep: Optional[Callable[[dict], None]] = None,
    on_sports: Optional[Callable[[dict], None]] = None,
    on_stress: Optional[Callable[[dict], None]] = None,
    on_progress: Optional[Callable[[FetchProgress], None]] = None,
) -> HistorySyncResult:
    """Fetch band-side history since *days* ago (or explicit *since_ts*/*until_ts*).

    Fetched samples are returned and optionally forwarded to the ``on_*``
    callbacks (used to persist them). A failure for one data type does not
    abort the other; errors are collected in :attr:`HistorySyncResult.errors`.

    ``include_spo2_sleep`` requests type ``0x26``. Its 30-byte layout is
    hardware-verified but the trailing fields are undocumented, so it stays off
    by default and consumers should treat those samples as capture material,
    not as validated measurements.
    """
    result = HistorySyncResult()
    if not (include_spo2 or include_activity or include_spo2_sleep
            or include_sports or include_stress):
        return result

    tz = resolve_band_tz(band_tz)
    fetcher = BandHistoryFetcher(client, timeout=timeout, band_tz=tz)
    if since_ts is not None:
        since = datetime.fromtimestamp(float(since_ts), tz=tz).replace(
            second=0, microsecond=0
        )
    else:
        since = (datetime.now(tz) - timedelta(days=max(0, int(days)))).replace(
            second=0, microsecond=0
        )
    now_ts = time.time()

    # Build the candidate task list, then pass it through the capability gate.
    # A type a real device already answered "accepted, zero records" for (or
    # that needs a per-summary id) is skipped here, so sync never re-probes a
    # known-empty type on every run. See history/capabilities.py.
    candidates: list[tuple[FetchDataType, str, Callable[[list[dict]], None]]] = []
    if include_activity:
        candidates.append((FetchDataType.ACTIVITY, "activity", _extend_activity))
    if include_spo2:
        candidates.append((FetchDataType.SPO2_NORMAL, "spo2", _extend_spo2))
    if include_spo2_sleep:
        candidates.append((FetchDataType.SPO2_SLEEP, "spo2_sleep", _extend_spo2_sleep))
    if include_sports:
        candidates.append((FetchDataType.SPORTS_SUMMARIES, "sports", _extend_sports))
    if include_stress:
        candidates.append((FetchDataType.STRESS_AUTOMATIC, "stress", _extend_stress))

    tasks: list[tuple[FetchDataType, str, Callable[[list[dict]], None]]] = []
    for data_type, name, append in candidates:
        if is_skippable(data_type):
            logger.info("Skipping known-empty/unsupported history type %#04x (%s)", int(data_type), name)
            continue
        tasks.append((data_type, name, append))

    consumers: dict[FetchDataType, Optional[Callable[[dict], None]]] = {
        FetchDataType.ACTIVITY: on_activity,
        FetchDataType.SPO2_NORMAL: on_spo2,
        FetchDataType.SPO2_SLEEP: on_spo2_sleep,
        FetchDataType.SPORTS_SUMMARIES: on_sports,
        FetchDataType.STRESS_AUTOMATIC: on_stress,
    }

    for data_type, name, append in tasks:
        current = since
        previous_last_ts: Optional[float] = None
        result.rounds.setdefault(name, 0)
        # B-6: fetch with progress + bounded link recovery; parsing goes
        # through the plug-in registry so new types need no sync-loop edits.
        for _round in range(max(1, max_rounds)):
            try:
                payload, start_timestamp = await fetch_with_recovery(
                    fetcher, data_type, current, on_progress=on_progress
                )
            except Exception as exc:
                message = f"{name} fetch failed: {exc}"
                logger.error(message)
                result.errors.append(message)
                break

            if not payload:
                break
            try:
                samples = parse_with(data_type, payload, start_timestamp)
            except HistoryParseError as exc:
                message = f"{name} payload parse failed: {exc}"
                logger.error(message)
                result.errors.append(message)
                break

            if not samples:
                break
            last_ts = max(sample["ts"] for sample in samples)
            if not _timestamp_usable(last_ts):
                message = f"{name} returned an out-of-range timestamp ({last_ts!r})"
                logger.error(message)
                result.errors.append(message)
                break
            if previous_last_ts is not None and last_ts <= previous_last_ts:
                logger.info("No forward progress in %s fetch; stopping.", name)
                break
            previous_last_ts = last_ts

            min_ts = since.timestamp() if since_ts is not None else None
            emit_samples = [
                sample
                for sample in samples
                if (min_ts is None or sample["ts"] >= min_ts)
                and (until_ts is None or sample["ts"] <= until_ts)
            ]

            if emit_samples:
                result.rounds[name] += 1
                append(result, emit_samples)

                callback = consumers.get(data_type)
                if callback is not None:
                    for sample in emit_samples:
                        try:
                            callback(sample)
                        except Exception:  # pragma: no cover - consumer errors must not abort
                            logger.exception("History sample consumer failed")

                logger.info(
                    "Fetched %d %s sample(s) up to %s",
                    len(emit_samples),
                    name,
                    _format_ts(max(s["ts"] for s in emit_samples), tz=tz),
                )
            if data_type == FetchDataType.ACTIVITY and last_ts > now_ts + 1800:
                logger.warning(
                    "Activity timestamps appear %.1fh ahead of host UTC; if the band "
                    "uses a different local timezone (e.g. Asia/Shanghai on a UTC host), "
                    "pass --band-tz or set BAND_TZ in .env so activity and SpO2 align.",
                    (last_ts - now_ts) / 3600.0,
                )
            if data_type == FetchDataType.SPORTS_SUMMARIES:
                # The band selects the next summary by its END time (Gadgetbridge
                # stores lastSync = summary.endTime); advancing by start+1s makes
                # it return the same record forever.
                cursor_ts = max(
                    float(sample.get("end_ts") or sample["ts"]) for sample in samples
                )
                next_current = datetime.fromtimestamp(cursor_ts + 1, tz=tz)
                if cursor_ts <= current.timestamp():
                    break
            else:
                next_current = (
                    datetime.fromtimestamp(last_ts, tz=tz) + timedelta(minutes=1)
                ).replace(second=0, microsecond=0)
                if last_ts <= current.timestamp() + 60 or last_ts >= now_ts - 60:
                    break
            if until_ts is not None and next_current.timestamp() > until_ts:
                break
            current = next_current

    return result


def _extend_activity(result: HistorySyncResult, samples: list[dict]) -> None:
    result.activity.extend(samples)


def _extend_spo2(result: HistorySyncResult, samples: list[dict]) -> None:
    result.spo2.extend(samples)


def _extend_spo2_sleep(result: HistorySyncResult, samples: list[dict]) -> None:
    result.spo2_sleep.extend(samples)


def _extend_stress(result: HistorySyncResult, samples: list[dict]) -> None:
    result.stress.extend(samples)


def _extend_sports(result: HistorySyncResult, samples: list[dict]) -> None:
    result.sports.extend(samples)


def summarize_history_result(result: HistorySyncResult) -> str:
    """Human-readable one-line summary used by the CLI."""
    if not result.total_samples and not result.errors:
        return "no new history data"
    parts = [f"{len(result.activity)} activity sample(s)", f"{len(result.spo2)} SpO2 sample(s)"]
    # Only mention the opt-in type when it actually ran, so the default log line
    # stays byte-for-byte compatible with existing tooling and tests.
    if result.spo2_sleep or "spo2_sleep" in result.rounds:
        parts.append(f"{len(result.spo2_sleep)} sleep SpO2 sample(s) [experimental]")
    if result.stress or "stress" in result.rounds:
        parts.append(f"{len(result.stress)} stress reading(s)")
    if result.sports or "sports" in result.rounds:
        parts.append(f"{len(result.sports)} workout summary(ies)")
    if result.rounds:
        parts.append(
            "rounds=" + ",".join(f"{name}:{count}" for name, count in sorted(result.rounds.items()))
        )
    if result.errors:
        parts.append(f"errors={len(result.errors)}")
    return ", ".join(parts)
