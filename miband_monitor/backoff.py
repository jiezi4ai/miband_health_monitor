"""Bounded exponential backoff, shared by BLE transactions, fetch recovery and reconnects.

Gadgetbridge's ``AutoConnectIntervalReceiver`` doubles a delay and caps it at
64 s (``mDelay = Math.min(mDelay * 2, 64000)``), plus an immediate-reconnect
branch for the first fast retry. That is the strategy **reused** here (protocol
pattern only, independent implementation): no fixed-interval polling. The helper
is pure and dependency-free so every layer can share one policy.
"""

from __future__ import annotations


class ExponentialBackoff:
    """Doubling delay with a hard cap and reset.

    ``next_delay()`` returns the current delay then doubles it for the next
    call, never exceeding *cap*. Pass ``immediate_first=True`` for GB's
    fast-reconnect branch: the first call returns 0 (retry now), subsequent
    calls follow the capped doubling.
    """

    def __init__(
        self,
        initial: float,
        cap: float,
        *,
        immediate_first: bool = False,
    ) -> None:
        self.initial = max(0.0, float(initial))
        self.cap = max(self.initial, float(cap))
        self.immediate_first = bool(immediate_first)
        self.reset()

    def reset(self) -> None:
        """Return to the initial delay (call after a success)."""
        self._delay = self.initial
        self._first = True

    def next_delay(self) -> float:
        """Return the delay to wait before the next attempt."""
        if self.immediate_first and self._first:
            self._first = False
            return 0.0
        self._first = False
        delay = min(self._delay, self.cap)
        self._delay = min(self._delay * 2.0, self.cap)
        return delay

    @property
    def pending_delay(self) -> float:
        """The delay that would be returned next, without consuming it."""
        if self.immediate_first and self._first:
            return 0.0
        return min(self._delay, self.cap)
