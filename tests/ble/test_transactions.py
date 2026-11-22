"""B-5: GATT transaction queue semantics."""

from __future__ import annotations

import asyncio

import pytest

from miband_monitor.backoff import ExponentialBackoff
from miband_monitor.ble import (
    ActionFailed,
    CallbackLatch,
    GattTransactionQueue,
    TransactionAborted,
    TransactionBuilder,
)
from miband_monitor.bluez.errors import is_transient_connect_error


# ---------------------------------------------------------------------------
# Bounded exponential backoff (GB strategy, not fixed interval)
# ---------------------------------------------------------------------------
def test_backoff_doubles_and_caps():
    backoff = ExponentialBackoff(initial=0.15, cap=1.0)
    assert backoff.next_delay() == pytest.approx(0.15)
    assert backoff.next_delay() == pytest.approx(0.30)
    assert backoff.next_delay() == pytest.approx(0.60)
    assert backoff.next_delay() == pytest.approx(1.0)  # capped, not 1.2
    assert backoff.next_delay() == pytest.approx(1.0)


def test_backoff_reset_and_immediate_first():
    backoff = ExponentialBackoff(0.5, 4.0, immediate_first=True)
    assert backoff.next_delay() == 0.0  # GB's fast-reconnect branch
    assert backoff.next_delay() == pytest.approx(0.5)
    backoff.reset()
    assert backoff.next_delay() == 0.0


# ---------------------------------------------------------------------------
# Ordered actions and abort-on-failure
# ---------------------------------------------------------------------------
async def test_transaction_runs_actions_in_order():
    order: list[str] = []

    def step(name: str):
        async def op(_client):
            order.append(name)
            return name
        return op

    builder = TransactionBuilder("ordered")
    builder.step("a", step("a")).step("b", step("b")).step("c", step("c"))
    queue = GattTransactionQueue(asyncio.Lock())
    results = await queue.run(builder.build(), object())
    assert order == ["a", "b", "c"]
    assert results == ["a", "b", "c"]
    assert queue.stats["succeeded"] == 1


async def test_transaction_aborts_on_first_failure():
    ran: list[str] = []

    def ok(name):
        async def op(_client):
            ran.append(name)
        return op

    async def fail(_client):
        ran.append("fail")
        raise ValueError("boom")

    builder = TransactionBuilder("abort")
    builder.step("first", ok("first")).step("bad", fail).step("never", ok("never"))
    queue = GattTransactionQueue(asyncio.Lock(), max_retries=0)
    with pytest.raises(TransactionAborted, match="aborted at step 1"):
        await queue.run(builder.build(), object())
    assert ran == ["first", "fail"]  # third action never ran
    assert queue.stats["aborted"] == 1


async def test_action_failed_carries_original():
    async def fail(_client):
        raise ValueError("boom")

    builder = TransactionBuilder("x").step("bad", fail)
    queue = GattTransactionQueue(asyncio.Lock(), max_retries=0)
    with pytest.raises(TransactionAborted) as exc:
        await queue.run(builder.build(), object())
    assert isinstance(exc.value.__cause__, ValueError)


# ---------------------------------------------------------------------------
# Link error: clear queue + bounded backoff retry
# ---------------------------------------------------------------------------
async def test_link_error_retries_with_backoff_then_succeeds():
    attempts = {"n": 0}

    async def flaky(_client):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("org.bluez.Error.InProgress")
        return "ok"

    queue = GattTransactionQueue(
        asyncio.Lock(), initial_backoff=0.001, max_backoff=0.002, max_retries=2
    )
    builder = TransactionBuilder("retry").step("flaky", flaky)
    results = await queue.run(builder.build(), object())
    assert results == ["ok"]
    assert attempts["n"] == 2
    assert queue.stats["retries"] == 1
    assert queue.stats["cleared"] == 1
    assert queue.stats["succeeded"] == 1


async def test_non_transient_error_is_not_retried():
    attempts = {"n": 0}

    async def fail(_client):
        attempts["n"] += 1
        raise ValueError("permanent business error")

    queue = GattTransactionQueue(asyncio.Lock(), initial_backoff=0.001, max_retries=2)
    with pytest.raises(TransactionAborted):
        await queue.run(TransactionBuilder("x").step("bad", fail).build(), object())
    assert attempts["n"] == 1  # no retry for a non-link error


async def test_queued_transaction_is_cleared_on_link_error(monkeypatch):
    """A pending transaction sees the generation bump and aborts without running."""
    gate = asyncio.Event()
    ran = {"second": False}

    async def first(_client):
        await gate.wait()
        raise RuntimeError("device disconnected")  # transient link error

    async def second(_client):
        ran["second"] = True

    queue = GattTransactionQueue(asyncio.Lock(), initial_backoff=0.001, max_retries=0)
    t1 = asyncio.create_task(queue.run(TransactionBuilder("t1").step("a", first).build(), object()))
    await asyncio.sleep(0)  # t1 acquires lock and blocks on gate
    t2 = asyncio.create_task(queue.run(TransactionBuilder("t2").step("b", second).build(), object()))
    await asyncio.sleep(0)
    gate.set()
    with pytest.raises(TransactionAborted):
        await t1
    with pytest.raises(TransactionAborted, match="queue cleared"):
        await t2
    assert ran["second"] is False
    assert queue.pending == 0


# ---------------------------------------------------------------------------
# Callback latch
# ---------------------------------------------------------------------------
async def test_callback_latch_releases_waiter():
    latch = CallbackLatch()
    assert not latch.released

    async def notify_later():
        await asyncio.sleep(0.01)
        latch.release({"bpm": 72})

    asyncio.create_task(notify_later())
    payload = await latch.wait(timeout=1.0)
    assert payload == {"bpm": 72}
    assert latch.released


async def test_callback_latch_times_out():
    latch = CallbackLatch()
    with pytest.raises(asyncio.TimeoutError):
        await latch.wait(timeout=0.01)


def test_link_error_helper_recognises_known_errors():
    assert is_transient_connect_error(RuntimeError("org.bluez.Error.InProgress"))
    assert not is_transient_connect_error(ValueError("permanent"))
