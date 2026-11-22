"""Session supervisor: connect, stream, reconnect and demo mode.

The logic is moved verbatim from miband_client.py. It intentionally stays in the
CLI package because it wires a user-facing session (duration, reconnects, IMU,
history sync) rather than implementing BLE protocol details.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

from ..ble.client import MiBand6Client, StreamCallbacks
from ..ble.device_state import DeviceState
from ..ble.discovery import AdapterDeafError
from ..ble.time_sync import maybe_sync_time
from ..bluez.errors import describe_ble_error
from ..config.defaults import (
    DEFAULT_ADAPTER_DEAF_LIMIT,
    DEFAULT_BATTERY_POLL_SECONDS,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_HR_SILENCE_HARD_SECONDS,
    DEFAULT_HR_SILENCE_SOFT_SECONDS,
    DEFAULT_RECONNECT_FAST_DELAY,
    DEFAULT_RECONNECT_INITIAL_DELAY,
    DEFAULT_RECONNECT_MAX_DELAY,
    DEFAULT_SCAN_TIMEOUT,
    ENV_ADAPTER_DEAF_LIMIT,
)
from ..config.env import env_int
from ..dashboard import TelemetryHub
from ..history.sync import summarize_history_result, sync_history
from ..workout import WorkoutSession
from .workout_runner import (
    handle_workout_connected,
    handle_workout_disconnected,
    handle_workout_finish,
    wait_session_with_battery,
)

logger = logging.getLogger("MiBand6Client")


async def _sync_band_history(
    client: MiBand6Client,
    days: int,
    callbacks: StreamCallbacks,
    *,
    include_spo2_sleep: bool = False,
    include_sports: bool = False,
    include_stress: bool = False,
    band_tz: Optional[str] = None,
) -> None:
    """Fetch band-side history once; failures never abort live streaming."""
    logger.info("Fetching up to %d day(s) of band-side history (experimental)...", days)
    if include_spo2_sleep:
        logger.warning(
            "Sleep SpO2 (0x26) capture enabled: 30B layout verified, trailing "
            "fields unknown; samples go to spo2_sleep, never point spo2.")
    client.device_state.set_busy("fetch activity data")
    try:
        result = await sync_history(
            client,
            days=days,
            on_spo2=callbacks.history_spo2, on_activity=callbacks.history_activity,
            include_spo2_sleep=include_spo2_sleep, on_spo2_sleep=callbacks.history_spo2_sleep,
            include_sports=include_sports, on_sports=callbacks.history_sports,
            include_stress=include_stress, on_stress=callbacks.history_stress,
            band_tz=band_tz,
        )
    except Exception as exc:
        logger.error("Band history sync failed (continuing with live streams): %s", exc)
        return
    finally:
        client.device_state.clear_busy()
    logger.info("Band history sync finished: %s", summarize_history_result(result))
    for error in result.errors:
        logger.warning("History sync issue: %s", error)


async def run_monitor(
    device_id: str,
    auth_key_hex: str,
    *,
    duration: Optional[int] = None,
    imu: bool = False,
    callbacks: Optional[StreamCallbacks] = None,
    scan_timeout: float = DEFAULT_SCAN_TIMEOUT,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    reconnect: bool = True,
    reconnect_initial_delay: float = DEFAULT_RECONNECT_INITIAL_DELAY,
    reconnect_max_delay: float = DEFAULT_RECONNECT_MAX_DELAY,
    sync_history_days: Optional[int] = None,
    sync_sleep_spo2: bool = False,
    sync_sports: bool = False,
    sync_stress: bool = False,
    time_sync: Optional[str] = None,
    band_tz: Optional[str] = None,
    device_name: Optional[str] = None,
    mtu: Optional[int] = None,
    direct_connect: bool = True,
    hr_silence_soft: float = DEFAULT_HR_SILENCE_SOFT_SECONDS,
    hr_silence_hard: float = DEFAULT_HR_SILENCE_HARD_SECONDS,
    workout: Optional[WorkoutSession] = None,
    hub: Optional[TelemetryHub] = None,
    battery_interval: float = DEFAULT_BATTERY_POLL_SECONDS,
    workout_reconcile: bool = True,
    adapter_deaf_limit: Optional[int] = None,
    client_factory: Optional[Callable[[str, str], MiBand6Client]] = None,
) -> None:
    """Connect + stream until duration elapses, reconnecting with backoff."""
    callbacks = callbacks or StreamCallbacks()
    make_client = client_factory or (
        lambda device, key: MiBand6Client(
            device,
            key,
            device_name=device_name,
            mtu=mtu,
            scan_timeout=scan_timeout,
            connect_timeout=connect_timeout,
            direct_connect=direct_connect,
            hr_silence_soft_seconds=hr_silence_soft,
            hr_silence_hard_seconds=hr_silence_hard,
        )
    )
    pre_auth_deadline = None if duration is None else time.monotonic() + duration
    collection_deadline: Optional[float] = None
    attempt = 0
    consecutive_failures = 0
    succeeded_sessions = 0
    last_failure: Optional[BaseException] = None
    history_synced = False
    unresolved_drop_streak = 0
    stale_bond_reset_done = False
    adapter_deaf_streak = 0
    deaf_limit = (
        env_int(ENV_ADAPTER_DEAF_LIMIT, DEFAULT_ADAPTER_DEAF_LIMIT)
        if adapter_deaf_limit is None
        else int(adapter_deaf_limit)
    )

    while True:
        active_deadline = (
            collection_deadline if collection_deadline is not None else pre_auth_deadline
        )
        remaining = None if active_deadline is None else active_deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            if collection_deadline is not None:
                logger.info("Collection window (%ss) elapsed.", duration)
                return
            if succeeded_sessions == 0 and last_failure is not None:
                raise last_failure
            return

        attempt += 1
        client = make_client(device_id, auth_key_hex)
        # B-4 / B-14: route device events through the shared hub channel.
        if hub is not None and hasattr(client, "attach_event_publisher"):
            client.attach_event_publisher(hub.publish_event)
        if hasattr(client, "device_state"):
            if attempt > 1:
                client.device_state.note_reconnect()
            client.set_device_state(DeviceState.CONNECTING)
        if hasattr(client, "_unresolved_drops"):
            client._unresolved_drops = unresolved_drop_streak
        if stale_bond_reset_done and hasattr(client, "_stale_bond_reset_attempted"):
            client._stale_bond_reset_attempted = True
            if hasattr(client, "_auto_enable_pairing_agent"):
                client._auto_enable_pairing_agent = True
        if adapter_deaf_streak >= 1 and hasattr(client, "_direct_connect"):
            client._direct_connect = False
            logger.info("Skipping direct connect probe after 0-packet scan; checking RX via scan...")
        failure: Optional[BaseException] = None
        was_authenticated = False
        try:
            await client.connect_and_authenticate(scan_timeout=scan_timeout)
            if hasattr(client, "set_device_state"):
                client.set_device_state(DeviceState.CONNECTED)
            was_authenticated = True
            unresolved_drop_streak = 0
            adapter_deaf_streak = 0
            succeeded_sessions += 1
            consecutive_failures = 0
            if time_sync is not None:
                await maybe_sync_time(client, dry_run=time_sync != "apply", tz=band_tz)
            if duration is not None and collection_deadline is None:
                # Count --duration as collection time after first authentication
                # rather than letting BLE scan/connect consume the window.
                collection_deadline = time.monotonic() + duration

            if sync_history_days is not None and not history_synced:
                await _sync_band_history(
                    client,
                    sync_history_days,
                    callbacks,
                    include_spo2_sleep=sync_sleep_spo2,
                    include_sports=sync_sports,
                    include_stress=sync_stress,
                    band_tz=band_tz,
                )
                history_synced = True
            await handle_workout_connected(
                client, workout, callbacks, attempt=attempt, band_tz=band_tz, hub=hub,
            )
            if hasattr(client, "set_device_state"):
                client.set_device_state(DeviceState.INITIALIZING)
            # Mi Band 6 starves HR notifications unless the raw sensor hub is woken first.
            start_sensor = getattr(client, "start_raw_sensor_stream", None)
            if callable(start_sensor):
                await start_sensor(callbacks.imu if imu else None)
            await client.start_heart_rate_stream(callbacks.heart_rate)
            await client.start_steps_stream(callbacks.steps)
            if hasattr(client, "set_device_state"):
                client.set_device_state(DeviceState.INITIALIZED)
            duration_note = f"{duration}s" if duration is not None else "until Ctrl+C"
            logger.info("Streaming session %d started (duration=%s, imu=%s).", attempt, duration_note, imu)

            remaining = None if collection_deadline is None else collection_deadline - time.monotonic()
            outcome = await wait_session_with_battery(
                client,
                remaining,
                workout,
                battery_interval=battery_interval,
                hub=hub,
                wait_for_fn=asyncio.wait_for,
            )
            if outcome == "timeout":
                logger.info("Collection window (%ss) elapsed.", duration)
                await handle_workout_finish(
                    client,
                    workout,
                    callbacks,
                    band_tz=band_tz,
                    hub=hub,
                    reconcile=workout_reconcile,
                )
                return
            failure = RuntimeError("BLE link lost")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = exc
            last_failure = exc
            logger.error("Session %d failed: %s", attempt, describe_ble_error(exc))
            if isinstance(exc, AdapterDeafError):
                adapter_deaf_streak += 1
                if deaf_limit > 0 and succeeded_sessions == 0 and adapter_deaf_streak >= deaf_limit:
                    drop_note = f" (saw {unresolved_drop_streak} unresolved drop(s) earlier)" if unresolved_drop_streak > 0 else ""
                    logger.error("Aborting after %d consecutive 0-packet scans%s; reset adapter.", adapter_deaf_streak, drop_note)
                    raise
                if succeeded_sessions > 0 and adapter_deaf_streak >= 2:
                    logger.error("Adapter saw 0 BLE packets for %d consecutive scans since disconnect; USB reset may be needed.", adapter_deaf_streak)
            else:
                adapter_deaf_streak = 0
        finally:
            if was_authenticated and failure is not None:
                handle_workout_disconnected(workout, hub=hub)
            elif not was_authenticated:
                if getattr(client, "_stale_bond_reset_attempted", False):
                    stale_bond_reset_done = True
                    unresolved_drop_streak = 0
                elif isinstance(getattr(client, "_unresolved_drops", None), int):
                    unresolved_drop_streak = client._unresolved_drops
            await client.disconnect()
            if hasattr(client, "device_state"):
                client.device_state.reset()

        if not reconnect:
            if failure is not None and not was_authenticated:
                raise failure
            return

        if was_authenticated and failure is not None:
            # When an established session drops, the band advertises aggressively
            # for a few seconds. Fast-reconnect immediately to catch that window
            # without waking the screen.
            delay = min(DEFAULT_RECONNECT_FAST_DELAY, reconnect_initial_delay)
        else:
            consecutive_failures += 1
            delay = min(
                reconnect_max_delay,
                reconnect_initial_delay * (2 ** min(consecutive_failures - 1, 5)),
            )
        active_deadline = (
            collection_deadline if collection_deadline is not None else pre_auth_deadline
        )
        remaining = None if active_deadline is None else active_deadline - time.monotonic()
        if remaining is not None:
            if remaining <= 0:
                if succeeded_sessions == 0 and last_failure is not None:
                    raise last_failure
                return
            delay = min(delay, remaining)
        logger.info("Reconnecting in %.2fs (next attempt %d)...", delay, attempt + 1)
        if delay > 0:
            await asyncio.sleep(delay)

from .demo_runner import run_demo  # noqa: E402,F401  (public re-export)
