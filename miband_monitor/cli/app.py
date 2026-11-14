"""Main entry point behind miband_client.py.

The orchestration is moved verbatim from the former monolithic module: parse
arguments, configure logging, optionally run the doctor, validate the device
credentials, wire storage + optional live dashboard, then run the real or
simulated session and export CSV on shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
from pathlib import Path
from typing import Optional

from ..ble.identity import is_placeholder_device_id, normalize_auth_key
from ..bluez.platform import is_bluez_platform
from ..config.demo import DEMO_AUTH_KEY_HEX, DEMO_DEVICE_ID
from ..config.defaults import (
    DEFAULT_MTU_MAX,
    DEFAULT_MTU_MIN,
    ENV_AUTH_KEY,
)
from ..config.env import env_str
from ..crypto.facade import backend_name as ecdh_backend_name
from ..dashboard import DashboardServer, TelemetryHub, make_db_history_provider
from ..diagnostics.checks import warn_usb_autosuspend_preflight
from ..history import resolve_band_tz
from ..storage import TelemetryStore
from ..storage.export_csv import export_database
from ..workout import WorkoutSession
from .args import demo_requested, parse_args
from .callbacks import build_callbacks
from .logging import configure_logging
from .runner import run_demo, run_monitor
from .workout_runner import (
    build_workout_profile,
    format_workout_summary,
    save_workout_summary,
)

logger = logging.getLogger("MiBand6Client")


async def _run_with_sigterm(awaitable) -> None:
    """Await *awaitable* in a sub-task so SIGTERM triggers clean teardown."""
    task = asyncio.ensure_future(awaitable)
    loop = asyncio.get_running_loop()
    sigterm_received = False

    def _on_sigterm() -> None:
        nonlocal sigterm_received
        if sigterm_received:
            return
        sigterm_received = True
        logger.info("Received SIGTERM; shutting down cleanly...")
        task.cancel()

    registered = False
    if hasattr(signal, "SIGTERM"):
        try:
            loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
            registered = True
        except (NotImplementedError, RuntimeError):
            registered = False
    try:
        await task
    except asyncio.CancelledError:
        if not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        if sigterm_received:
            return
        raise
    finally:
        if registered:
            with contextlib.suppress(Exception):
                loop.remove_signal_handler(signal.SIGTERM)


async def main(argv: Optional[list[str]] = None) -> int:
    """Run the CLI; returns a process exit code (0 success, 1 failure)."""
    args = parse_args(argv)
    configure_logging(args.log_level)

    if args.doctor:
        # Imported lazily: doctor imports configuration helpers itself.
        from ..diagnostics.doctor import run_doctor

        return await run_doctor(
            (args.device_id or "").strip(),
            env_str(ENV_AUTH_KEY),
            args.output,
        )

    if getattr(args, "gui", False):
        from ..gui.app import run_gui_server

        port = 8080 if args.web_port is None else args.web_port
        return await run_gui_server(
            host=args.web_host,
            port=port,
            output_dir=args.output,
            storage_backend=args.storage,
            open_browser=True,
            auto_connect=False,
            demo=demo_requested(args),
        )

    logger.info("ECDH backend: %s", ecdh_backend_name())

    device_id = (args.device_id or "").strip()
    device_name = (args.device_name or "").strip() or None
    key = env_str(ENV_AUTH_KEY)
    demo = demo_requested(args)

    if args.mtu is not None and not (DEFAULT_MTU_MIN <= args.mtu <= DEFAULT_MTU_MAX):
        logger.error(
            "Invalid --mtu %s: ATT MTU must be between %d and %d bytes. "
            "Leave it unset to auto-detect.",
            args.mtu,
            DEFAULT_MTU_MIN,
            DEFAULT_MTU_MAX,
        )
        return 1

    band_tz = (getattr(args, "band_tz", "") or "").strip() or None
    if band_tz is not None:
        try:
            resolve_band_tz(band_tz)
        except ValueError as exc:
            logger.error("Invalid --band-tz %r: %s", band_tz, exc)
            return 1

    if demo:
        if is_placeholder_device_id(device_id):
            device_id = DEMO_DEVICE_ID
        try:
            normalize_auth_key(key)
        except ValueError:
            logger.warning(
                "DEMO_MODE: no valid AUTH_KEY configured; using throwaway demo key."
            )
            key = DEMO_AUTH_KEY_HEX
    else:
        if is_placeholder_device_id(device_id) or not key or key.startswith("012345"):
            logger.error(
                "Please configure DEVICE_ID (Bluetooth address, or macOS UUID) "
                "and AUTH_KEY in .env before running (or run with --demo). "
                "Legacy DEVICE_MAC is still accepted."
            )
            return 1
        try:
            normalize_auth_key(key)
        except ValueError as exc:
            logger.error("Invalid AUTH_KEY: %s", exc)
            return 1

    logger.info(
        "Discovery target: %s%s",
        device_id,
        f" (name filter: {device_name!r})" if device_name else "",
    )

    store = TelemetryStore(args.output, backend=args.storage)

    hub: Optional[TelemetryHub] = None
    web_server: Optional[DashboardServer] = None
    if args.web_port is not None:
        hub = TelemetryHub()
        hub.attach_loop(asyncio.get_running_loop())
        web_server = DashboardServer(
            hub,
            host=args.web_host,
            port=args.web_port,
            history_provider=make_db_history_provider(store.db_path),
        )
        try:
            await web_server.start()
            logger.info("Live dashboard: %s", web_server.url)
        except OSError as exc:
            logger.error(
                "Could not start the dashboard on %s:%s: %s",
                args.web_host,
                args.web_port,
                exc,
            )
            web_server = None
            hub = None

    workout: Optional[WorkoutSession] = None
    if getattr(args, "workout", False):
        workout = WorkoutSession(
            build_workout_profile(args),
            gap_fill_min_seconds=args.gap_fill_min,
        )
        if hub is not None:
            hub.publish_workout(workout.snapshot(timeline_limit=300))

    callbacks = build_callbacks(store, hub, workout=workout)
    if args.storage == "none":
        logger.info("Storage disabled; telemetry will only be logged.")
    else:
        logger.info(
            "Telemetry output: backend=%s -> %s",
            args.storage,
            Path(args.output).resolve(),
        )

    if not demo and is_bluez_platform():
        warn_usb_autosuspend_preflight(logger)

    exit_code = 0
    try:
        if demo:
            coro = run_demo(
                device_id,
                key,
                duration=args.duration,
                imu=args.imu,
                callbacks=callbacks,
                sync_history_days=args.sync_history,
                sync_sleep_spo2=args.sync_sleep_spo2,
                band_tz=band_tz,
                mtu=args.mtu,
                hr_silence_soft=args.hr_silence_soft,
                hr_silence_hard=args.hr_silence_hard,
                workout=workout,
                hub=hub,
                battery_interval=args.battery_interval,
            )
        else:
            coro = run_monitor(
                device_id,
                key,
                duration=args.duration,
                imu=args.imu,
                callbacks=callbacks,
                scan_timeout=args.scan_timeout,
                connect_timeout=args.connect_timeout,
                reconnect=not args.no_reconnect,
                sync_history_days=args.sync_history,
                sync_sleep_spo2=args.sync_sleep_spo2,
                band_tz=band_tz,
                device_name=device_name,
                mtu=args.mtu,
                direct_connect=not args.no_direct_connect,
                hr_silence_soft=args.hr_silence_soft,
                hr_silence_hard=args.hr_silence_hard,
                workout=workout,
                hub=hub,
                battery_interval=args.battery_interval,
            )
        await _run_with_sigterm(coro)
    except KeyboardInterrupt:
        logger.info("Stopping on user request...")
    except Exception as exc:
        logger.error("Monitoring stopped after error: %s", exc)
        exit_code = 1
    finally:
        if workout is not None:
            summary = workout.finish() if workout.ended_at is None else workout.summary()
            if hub is not None:
                hub.publish_workout(summary)
            logger.info("%s", format_workout_summary(summary))
            if args.storage != "none":
                summary_path = save_workout_summary(args.output, summary)
                logger.info("Workout summary written -> %s", summary_path)
        if web_server is not None:
            try:
                await web_server.stop()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Error while stopping the dashboard: %s", exc)
        store.close()
        logger.info("Storage summary: %s", store.stats())
        if args.export_csv:
            if args.storage in ("sqlite", "both"):
                try:
                    exported = export_database(store.db_path, Path(args.output) / "csv")
                    for table, (path, rows) in exported.items():
                        logger.info("CSV export: %s (%d rows) -> %s", table, rows, path)
                except Exception as exc:
                    logger.error("CSV export failed: %s", exc)
            else:
                logger.warning(
                    "--export-csv requires --storage sqlite or both (current: %s)",
                    args.storage,
                )
    return exit_code
