"""Stale-bond recovery heuristics and BlueZ link-failure handling.

Kept separate from :mod:`miband_monitor.ble.link` so BlueZ recovery policy stays
modular, unit-testable, and well within per-file size budgets.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from .. import bluez
from ..config.defaults import DEFAULT_STALE_BOND_FAST_DROP_SECONDS

logger = logging.getLogger("MiBand6Client")


def has_fast_unresolved_drop(outcome: dict) -> bool:
    """Return True when outcome records an unresolved drop faster than ~9 s."""
    durations = outcome.get("unresolved_drop_durations") or []
    return any(float(dur) <= DEFAULT_STALE_BOND_FAST_DROP_SECONDS for dur in durations)


def should_attempt_stale_bond_recovery(
    *,
    total_unresolved_drops: int,
    had_prior_unresolved_drop: bool,
    outcome_ready: bool,
    recovery_already_attempted: bool,
) -> bool:
    """Return True when repeated failures indicate a stale cached BlueZ bond.

    Recovers once per client when either two unresolved pre-service drops are
    observed, or a follow-up link attempt fails after an earlier unresolved
    drop (so recovery still fires when the adapter subsequently times out
    instead of reaching a second Connected=True -> False cycle).
    """
    if outcome_ready or recovery_already_attempted:
        return False
    if total_unresolved_drops >= 2:
        return True
    return had_prior_unresolved_drop and total_unresolved_drops >= 1


def compute_scan_budget(
    remaining: float,
    scan_timeout: float,
    band_pulse_period: float,
    *,
    post_reset: bool = False,
) -> Optional[float]:
    """Return scan window budget in seconds, or None if too little deadline remains."""
    if not post_reset and remaining < 12.0:
        return None
    return max(remaining, min(float(scan_timeout), float(band_pulse_period)))


async def _reset_bluez_device_and_start_agent(
    client_owner: Any,
    *,
    reason_log: str,
) -> bool:
    """Remove cached BlueZ device state and start the pairing agent."""
    client_owner._stale_bond_reset_attempted = True
    logger.warning(reason_log, client_owner.device_id)
    if not await bluez.remove_device(client_owner.device_id):
        logger.warning("Could not remove stale BlueZ state for %s.", client_owner.device_id)
        return False
    client_owner._trusted_paths.clear()
    client_owner._reused_bluez_link = False
    client_owner._auto_enable_pairing_agent = True
    if client_owner._pairing_agent is None:
        agent = bluez.BlueZPairingAgent(client_owner.device_id)
        if await agent.start():
            client_owner._pairing_agent = agent
        else:
            logger.debug("BlueZ pairing agent failed to start during recovery.")
    return True


async def clear_stale_bond_and_start_agent(client_owner: Any) -> bool:
    """Clear a bonded BlueZ object via Adapter1.RemoveDevice and arm Agent1."""
    if getattr(client_owner, "_stale_bond_reset_attempted", False):
        return False
    if await bluez.paired_device(client_owner.device_id) is None:
        return False
    return await _reset_bluez_device_and_start_agent(
        client_owner,
        reason_log=(
            f"Detected {client_owner._unresolved_drops} consecutive unresolved "
            "BlueZ drops on bonded device %s (likely stale LTK); clearing cached "
            "BlueZ bond and enabling pairing agent for clean re-pair."
        ),
    )


async def handle_bluez_standby_failure(
    client_owner: Any,
    outcome: dict,
    *,
    prior_drops: int,
    scan_timeout: float,
    deadline: float,
    phases: list[str],
) -> tuple[bool, float]:
    """Update unresolved-drop tracking after a failed BlueZ standby window.

    Returns ``(recovered, updated_deadline)``; when ``recovered`` is True the
    caller should reset direct-device state and grant one recovery scan phase.
    """
    drops = int(outcome.get("dropped_unresolved", 0) or 0)
    if drops > 0:
        client_owner._unresolved_drops += drops
        if has_fast_unresolved_drop(outcome):
            logger.info(
                "Observed fast unresolved BlueZ drop (<= %.1fs), typical of stale LTK rejection.",
                DEFAULT_STALE_BOND_FAST_DROP_SECONDS,
            )

    recovered = False
    info = outcome.get("info") or {}
    if (
        outcome.get("reason") == "services-timeout"
        and not getattr(client_owner, "_stale_bond_reset_attempted", False)
        and info.get("path")
        and not info.get("paired")
        and not info.get("bonded")
    ):
        recovered = await _reset_bluez_device_and_start_agent(
            client_owner,
            reason_log=(
                "GATT service resolution timed out on half-paired BlueZ device %s; "
                "clearing incomplete cache and enabling pairing agent before retry."
            ),
        )
    elif should_attempt_stale_bond_recovery(
        total_unresolved_drops=client_owner._unresolved_drops,
        had_prior_unresolved_drop=prior_drops >= 1,
        outcome_ready=False,
        recovery_already_attempted=getattr(client_owner, "_stale_bond_reset_attempted", False),
    ):
        recovered = await client_owner._recover_from_stale_bond()

    if recovered:
        client_owner._unresolved_drops = 0
        new_deadline = max(
            deadline,
            time.monotonic()
            + min(float(scan_timeout), bluez.BAND_PULSE_PERIOD)
            + bluez.BAND_PULSE_PERIOD,
        )
        await asyncio.sleep(0.3)
        if "scan" not in phases:
            phases.append("scan")
        return True, new_deadline

    if drops > 0:
        logger.warning(
            "Link dropped before ServicesResolved (common when BlueZ holds a "
            "stale LTK after re-pairing elsewhere). Clear the cached bond "
            "with `bluetoothctl remove <MAC>` and reconnect with "
            "`MIBAND_BLUEZ_AGENT=1`."
        )
    return False, deadline
