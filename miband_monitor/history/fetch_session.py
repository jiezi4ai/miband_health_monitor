"""FetchSession: progress, error recovery and parser plug-in on the fetch template (B-6).

The existing :meth:`BandHistoryFetcher.fetch_payload` is already the unified
init -> metadata -> chunk -> CRC -> ack -> close template shared by all history
types (benchmark §7.3: do **not** re-extract it). This module adds the three
missing pieces without changing that template's behaviour:

* **progress callback** -- :class:`FetchProgress` snapshots emitted at phase
  boundaries (metadata / chunks / complete / ack);
* **error recovery** -- bounded exponential backoff retry of a whole fetch
  round on transient link errors, reusing :mod:`miband_monitor.backoff`;
* **parser plug-in** -- :class:`FetchParser` callable resolved from a registry,
  so B-12 (sports summaries) / B-13 (statistics) can add a type by registering
  a parser instead of editing the sync loop.

All additions are optional: existing callers of ``fetch_payload`` are unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional

from ..backoff import ExponentialBackoff
from ..bluez.errors import is_transient_connect_error
from .models import HistoryFetchError, HistoryParseError
from .protocol import FetchDataType, logger

#: A parser decodes a trimmed payload + start timestamp into sample dicts.
FetchParser = Callable[[bytes, float], list]


@dataclass(frozen=True)
class FetchProgress:
    """One progress snapshot from a fetch round."""

    phase: str  # "metadata" | "chunk" | "complete" | "ack" | "empty" | "error"
    data_type: int
    chunks: int = 0
    bytes_received: int = 0
    expected: Optional[int] = None
    note: str = ""


#: Parser registry keyed by fetch type. Pre-populated in __init__ to avoid a
#: circular import with the pure parsers module; callers can override/add.
PARSERS: Dict[FetchDataType, FetchParser] = {}


def register_parser(data_type: FetchDataType, parser: FetchParser) -> None:
    """Register (or replace) the parser used for a fetch data type."""
    PARSERS[FetchDataType(data_type)] = parser


def parse_with(data_type: FetchDataType, payload: bytes, start_timestamp: float) -> list:
    """Parse *payload* with the registered parser for *data_type*.

    Falls back to the built-in dispatch so existing types keep working even
    before the registry is populated. Raises :class:`HistoryParseError` when no
    parser is available for the type.
    """
    parser = PARSERS.get(FetchDataType(data_type))
    if parser is not None:
        return parser(payload, start_timestamp)
    from .parsers import _parse_payload  # lazy: avoids a module import cycle

    return _parse_payload(FetchDataType(data_type), payload, start_timestamp)


@dataclass
class FetchSession:
    """Holds per-round progress and parser choice for one history fetch type.

    The fetcher calls :meth:`progress` at phase boundaries; ``sync_history`` can
    attach a callback via ``on_progress``. ``parser`` lets a caller override the
    payload parser for experimental types without touching the sync loop.
    """

    data_type: FetchDataType
    on_progress: Optional[Callable[[FetchProgress], None]] = None
    parser: Optional[FetchParser] = None
    snapshots: list[FetchProgress] = field(default_factory=list)

    def progress(self, phase: str, **kwargs) -> None:
        snap = FetchProgress(phase=phase, data_type=int(self.data_type), **kwargs)
        self.snapshots.append(snap)
        if self.on_progress is not None:
            self.on_progress(snap)

    def parse(self, payload: bytes, start_timestamp: float) -> list:
        if self.parser is not None:
            return self.parser(payload, start_timestamp)
        return parse_with(self.data_type, payload, start_timestamp)


def parse_error(data_type: FetchDataType, message: str) -> HistoryParseError:
    """Helper for plug-in parsers that reject an unrecognised payload."""
    return HistoryParseError(f"{int(data_type):#04x}: {message}")


async def fetch_with_recovery(
    fetcher,
    data_type: FetchDataType,
    since: datetime,
    *,
    on_progress: Optional[Callable[[FetchProgress], None]] = None,
    parser: Optional[FetchParser] = None,
    max_retries: int = 2,
    initial_backoff: float = 0.2,
    max_backoff: float = 8.0,
) -> tuple[bytes, float]:
    """Run one fetch round with progress + bounded-backoff link recovery.

    Retries only transient link errors (never a protocol/business rejection),
    doubling the delay up to *max_backoff* -- the GB strategy, not a fixed
    interval. The fetch template itself is untouched; each retry is a fresh
    ``fetch_payload`` call. Non-transient errors propagate immediately.
    """
    session = FetchSession(data_type, on_progress=on_progress, parser=parser)
    backoff = ExponentialBackoff(initial_backoff, max_backoff)
    for attempt in range(max(0, max_retries) + 1):
        try:
            return await fetcher.fetch_payload(data_type, since, session=session)
        except Exception as exc:  # noqa: BLE001 - classify, then re-raise
            if not is_transient_connect_error(exc) or attempt >= max_retries:
                session.progress("error", note=str(exc))
                if isinstance(exc, HistoryFetchError):
                    raise
                raise HistoryFetchError(f"{data_type.name} fetch failed: {exc}") from exc
            delay = backoff.next_delay()
            session.progress("error", note="retry", expected=attempt + 1)
            logger.warning(
                "History %s link error; retry %d/%d in %.2fs: %s",
                data_type.name, attempt + 1, max_retries, delay, exc,
            )
            if delay:
                await asyncio.sleep(delay)
    raise HistoryFetchError(f"{data_type.name}: retries exhausted")  # pragma: no cover
