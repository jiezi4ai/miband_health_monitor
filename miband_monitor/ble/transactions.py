"""GATT transactions: an ordered action group serialized on one lock (B-5).

Gadgetbridge's ``BtLEQueue`` runs a ``Transaction`` (an ordered group of read /
write / subscribe actions) on a dedicated queue: one action at a time, each
awaited until its GATT callback, *any* action failure aborts the whole group, and
a link-level error clears pending work before a bounded exponential backoff
retry. This module re-implements that **pattern** independently (no GB code
copied) on top of the client's existing ``_gatt_lock``.

Design constraints (from benchmark §7.2 / §8):

* serialized on the existing lock -- no second, competing lock;
* connect/disconnect stay outside the queue (their own lifecycle lock);
* retry uses :class:`~miband_monitor.backoff.ExponentialBackoff` (doubling,
  capped), **not** the fixed interval the original benchmark text described;
* protocol bytes are unchanged -- grouping writes only tightens serialization
  and makes a failed group abort cleanly.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..backoff import ExponentialBackoff
from ..bluez.errors import is_transient_connect_error

logger = logging.getLogger("MiBandGatt")

#: One action receives the underlying GATT client and returns an optional value.
ActionOp = Callable[[Any], Awaitable[Any]]


@dataclass
class GattAction:
    """A single ordered step in a transaction."""

    name: str
    op: ActionOp


class ActionFailed(RuntimeError):
    """One action failed; carries the original cause and its index."""

    def __init__(self, name: str, index: int, original: BaseException) -> None:
        super().__init__(f"action {index} ({name}) failed: {original}")
        self.name = name
        self.index = index
        self.original = original


class TransactionAborted(RuntimeError):
    """The transaction did not complete (action failure or queue cleared)."""


@dataclass
class Transaction:
    """An ordered group of actions that succeed together or abort together."""

    name: str
    actions: list[GattAction] = field(default_factory=list)
    results: list[Any] = field(default_factory=list)

    async def execute(self, client: Any) -> list[Any]:
        """Run actions in order; the first failure aborts the rest."""
        self.results = []
        for index, action in enumerate(self.actions):
            logger.debug("Transaction %s step %d: %s", self.name, index, action.name)
            try:
                value = await action.op(client)
            except Exception as exc:  # noqa: BLE001 - any action failure aborts
                raise ActionFailed(action.name, index, exc) from exc
            self.results.append(value)
        return self.results


class TransactionBuilder:
    """Fluent assembly of a :class:`Transaction`."""

    def __init__(self, name: str) -> None:
        self._transaction = Transaction(name)

    def write(self, char_uuid: str, data: bytes, *, response: bool = False) -> "TransactionBuilder":
        """Add a raw GATT write action (the caller supplies the client)."""

        async def op(client: Any) -> None:
            await client.write_gatt_char(char_uuid, data, response=response)

        return self.step(f"write {char_uuid}", op)

    def read(self, char_uuid: str) -> "TransactionBuilder":
        async def op(client: Any) -> bytes:
            return bytes(await client.read_gatt_char(char_uuid))

        return self.step(f"read {char_uuid}", op)

    def wait_callback(self, latch: "CallbackLatch", *, timeout: Optional[float] = None) -> "TransactionBuilder":
        return self.step("wait callback", lambda _client: latch.wait(timeout))

    def step(self, name: str, op: ActionOp) -> "TransactionBuilder":
        self._transaction.actions.append(GattAction(name, op))
        return self

    def build(self) -> Transaction:
        return self._transaction


class CallbackLatch:
    """One-shot latch for a GATT notification callback (GB's CountDownLatch).

    A notification callback calls :meth:`release` with its payload; another
    coroutine awaits :meth:`wait`. No polling and no lost wakeups.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._payload: Any = None
        self._released = False

    def release(self, payload: Any = None) -> None:
        if not self._released:
            self._payload = payload
            self._released = True
            self._event.set()

    async def wait(self, timeout: Optional[float] = None) -> Any:
        await asyncio.wait_for(self._event.wait(), timeout=timeout)
        return self._payload

    @property
    def released(self) -> bool:
        return self._released


class GattTransactionQueue:
    """Serialize transactions on one lock with abort / clear / backoff semantics."""

    def __init__(
        self,
        lock: asyncio.Lock,
        *,
        initial_backoff: float = 0.15,
        max_backoff: float = 64.0,
        max_retries: int = 2,
    ) -> None:
        self.lock = lock
        self.backoff = ExponentialBackoff(initial_backoff, max_backoff)
        self.max_retries = max(0, int(max_retries))
        self._generation = 0
        self.pending = 0
        self.stats = {"succeeded": 0, "aborted": 0, "retries": 0, "cleared": 0}

    def clear(self) -> None:
        """Invalidate queued transactions (called on a link-level error)."""
        self._generation += 1
        self.stats["cleared"] += 1

    async def run(self, transaction: Transaction, client: Any) -> list[Any]:
        """Execute *transaction* under the shared lock, with link retry."""
        self.pending += 1
        generation = self._generation
        try:
            for attempt in range(self.max_retries + 1):
                if generation != self._generation:
                    raise TransactionAborted(f"{transaction.name}: queue cleared")
                try:
                    async with self.lock:
                        if generation != self._generation:
                            raise TransactionAborted(f"{transaction.name}: queue cleared")
                        results = await transaction.execute(client)
                except ActionFailed as failed:
                    original = failed.original
                    if is_transient_connect_error(original):
                        # GB: a link-level failure clears pending work first,
                        # then (when auto-reconnect is on) retries with backoff.
                        # Clearing happens even with retries disabled, so a
                        # queued transaction never runs on a broken link.
                        self.clear()
                        if attempt < self.max_retries:
                            generation = self._generation
                            delay = self.backoff.next_delay()
                            self.stats["retries"] += 1
                            logger.warning(
                                "Transaction %s link error on step %d; retry %d/%d in %.2fs",
                                transaction.name, failed.index, attempt + 1, self.max_retries, delay,
                            )
                            if delay:
                                await asyncio.sleep(delay)
                            continue
                    self.stats["aborted"] += 1
                    raise TransactionAborted(
                        f"{transaction.name} aborted at step {failed.index} ({failed.name})"
                    ) from original
                self.stats["succeeded"] += 1
                self.backoff.reset()
                return results
            raise TransactionAborted(f"{transaction.name}: retries exhausted")  # pragma: no cover
        finally:
            self.pending -= 1
