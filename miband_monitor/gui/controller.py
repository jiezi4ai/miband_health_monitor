"""Async session controller orchestrating BLE sessions, diagnostics and CSV export."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from bleak import BleakScanner

from ..ble.client import MiBand6Client
from ..ble.identity import _env_device_id
from ..bluez.errors import describe_ble_error
from ..cli.callbacks import build_callbacks
from ..cli.demo_runner import run_demo
from ..cli.runner import run_monitor
from ..cli.workout_runner import build_workout_profile, save_workout_summary
from ..config.defaults import (
    DEFAULT_DATA_DIR,
    DEFAULT_DB_FILENAME,
    ENV_AUTH_KEY,
    ENV_DEVICE_NAME,
    ENV_OUTPUT_DIR,
)
from ..config.env import load_env
from ..config.paths import default_csv_dir
from ..config.privacy import redact_text
from ..dashboard import TelemetryHub
from ..diagnostics import list_playbooks, recommend_playbooks, run_playbook
from ..storage import TelemetryStore
from ..storage.export_csv import export_database
from ..workout import WorkoutSession
from .config_manager import get_masked_config, resolve_session_options, update_gui_config
from .log_bridge import GuiLogBridge
from .state import GuiState

logger = logging.getLogger("MiBandGUI")


class GuiSessionController:
    """Own the background BLE/demo session and expose GUI control operations."""

    def __init__(
        self,
        hub: TelemetryHub,
        *,
        output_dir: Optional[str] = None,
        storage_backend: str = "both",
        env_path: Optional[Path] = None,
        scanner_factory: Optional[Callable[..., Any]] = None,
        demo_runner: Callable[..., Any] = run_demo,
        monitor_runner: Callable[..., Any] = run_monitor,
    ) -> None:
        self.hub = hub
        self.output_dir = (output_dir or os.getenv(ENV_OUTPUT_DIR) or DEFAULT_DATA_DIR).strip()
        self.storage_backend = storage_backend
        self.env_path = Path(env_path) if env_path is not None else None
        self._scanner_factory = scanner_factory or BleakScanner
        self._demo_runner = demo_runner
        self._monitor_runner = monitor_runner

        self.state = GuiState()
        self._session_task: Optional[asyncio.Task] = None
        self._log_bridge = GuiLogBridge(
            self.state, on_change=self._emit_state, on_log=self._emit_log
        )
        self._log_bridge.attach()
        self.hub.set_state_provider(self.snapshot)

    def close(self) -> None:
        self._log_bridge.detach()
        self.hub.set_state_provider(None)

    def _emit_state(self, _state_dict: Optional[dict] = None) -> None:
        self.hub.publish_event("gui_state", {"gui": self.snapshot()})

    def _emit_log(self, entry: dict[str, Any]) -> None:
        self.hub.publish_event("gui_log", {"entry": entry})

    def snapshot(self) -> dict[str, Any]:
        payload = self.state.to_dict()
        payload["config"] = get_masked_config(env_path=self.env_path, output_dir=self.output_dir)
        payload["playbooks"] = list_playbooks()
        return payload

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        cfg = update_gui_config(payload, env_path=self.env_path)
        self._emit_state()
        return cfg

    async def start_session(self, options: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if self._session_task is not None and not self._session_task.done():
            raise RuntimeError("A monitoring session is already active.")

        device_id, auth_key, opts = resolve_session_options(options, env_path=self.env_path)
        mode = "demo" if opts["demo"] else "real"
        self.state.reset_for_session(mode=mode, options=opts)
        self._emit_state()

        self._session_task = asyncio.create_task(
            self._run_session_task(device_id=device_id, auth_key=auth_key, opts=opts)
        )
        return self.snapshot()

    async def _run_session_task(
        self, *, device_id: str, auth_key: str, opts: dict[str, Any]
    ) -> None:
        store = TelemetryStore(self.output_dir, backend=self.storage_backend)
        workout: Optional[WorkoutSession] = None
        if opts["workout"]:
            profile = build_workout_profile(
                type("Args", (), {"age": 30, "weight": 70.0, "sex": "male", "hr_max": None})()
            )
            workout = WorkoutSession(profile)
            self.hub.publish_workout(workout.snapshot(timeline_limit=300))
        callbacks = build_callbacks(store, self.hub, workout=workout)
        arm_agent = self.state.arm_pairing_agent
        self.state.arm_pairing_agent = False

        def _client_factory(dev: str, key: str) -> MiBand6Client:
            client = MiBand6Client(
                dev,
                key,
                device_name=opts["device_name"],
                scan_timeout=opts["scan_timeout"],
                connect_timeout=opts["connect_timeout"],
                direct_connect=opts["direct_connect"],
            )
            if arm_agent:
                client._auto_enable_pairing_agent = True
            return client

        error_text: Optional[str] = None
        try:
            if opts["demo"]:
                await self._demo_runner(
                    device_id,
                    auth_key,
                    duration=opts["duration"],
                    imu=opts["imu"],
                    callbacks=callbacks,
                    sync_history_days=opts["sync_history_days"],
                    sync_sleep_spo2=opts["sync_sleep_spo2"],
                    band_tz=opts["band_tz"],
                    workout=workout,
                    hub=self.hub,
                )
            else:
                await self._monitor_runner(
                    device_id,
                    auth_key,
                    duration=opts["duration"],
                    imu=opts["imu"],
                    callbacks=callbacks,
                    scan_timeout=opts["scan_timeout"],
                    connect_timeout=opts["connect_timeout"],
                    reconnect=True,
                    sync_history_days=opts["sync_history_days"],
                    sync_sleep_spo2=opts["sync_sleep_spo2"],
                    band_tz=opts["band_tz"],
                    device_name=opts["device_name"],
                    direct_connect=opts["direct_connect"],
                    workout=workout,
                    hub=self.hub,
                    client_factory=_client_factory,
                )
        except asyncio.CancelledError:
            logger.info("GUI session stopped by user.")
        except Exception as exc:
            error_text = redact_text(describe_ble_error(exc))
            logger.error("GUI session failed: %s", error_text)
            self.state.add_recommendations(recommend_playbooks(error_text=error_text))
        finally:
            if workout is not None:
                summary = workout.finish() if workout.ended_at is None else workout.summary()
                self.hub.publish_workout(summary)
                if self.storage_backend != "none":
                    with contextlib.suppress(Exception):
                        save_workout_summary(self.output_dir, summary)
            store.close()
            self.state.mark_stopped(error=error_text)
            self._emit_state()

    async def stop_session(self) -> dict[str, Any]:
        task = self._session_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._session_task = None
        if self.state.running:
            self.state.mark_stopped()
            self._emit_state()
        return self.snapshot()

    async def run_doctor_check(self) -> dict[str, Any]:
        return await self.execute_playbook("doctor_check")

    async def execute_playbook(
        self, playbook_id: str, *, probe_duration: float = 15.0
    ) -> dict[str, Any]:
        if self.state.running and playbook_id not in ("doctor_check", "fix_env_permissions"):
            await self.stop_session()
        if self.env_path is not None and self.env_path.exists():
            load_env(self.env_path)
        device_id = _env_device_id()
        auth_key = (os.getenv(ENV_AUTH_KEY) or "").strip()
        device_name = (os.getenv(ENV_DEVICE_NAME) or "").strip() or None

        result = await run_playbook(
            playbook_id,
            device_id=device_id,
            auth_key=auth_key,
            output_dir=self.output_dir,
            device_name=device_name,
            probe_duration=probe_duration,
            env_path=self.env_path,
        )
        result_dict = result.to_dict()
        if playbook_id == "doctor_check":
            self.state.last_doctor = result_dict
            self.state.clear_recommendations()
            self.state.add_recommendations(result.recommended_next)
        else:
            self.state.last_playbook = result_dict
            if result.data.get("arm_pairing_agent"):
                self.state.arm_pairing_agent = True
            self.state.add_recommendations(result.recommended_next)
        logger.info("Playbook %s finished (%s): %s", playbook_id, result.status, result.summary)
        self.hub.publish_event("playbook_result", {"result": result_dict})
        self._emit_state()
        return result_dict

    async def quick_scan(self, duration: float = 12.0) -> dict[str, Any]:
        """Scan for nearby BLE devices so users can pick their Mi Band ID."""
        if self._session_task is not None and not self._session_task.done():
            raise RuntimeError("Stop the active monitoring session before scanning for devices.")
        timeout = max(3.0, min(float(duration), 60.0))
        kwargs: dict[str, Any] = {}
        if sys.platform.startswith("linux"):
            kwargs["bluez"] = {"filters": {"DuplicateData": True, "Transport": "le"}}
        discovered = await self._scanner_factory.discover(
            timeout=timeout, return_adv=True, **kwargs
        )
        items: list[dict[str, Any]] = []
        for dev, adv in discovered.values():
            name = getattr(dev, "name", None) or getattr(adv, "local_name", None) or "Unknown"
            rssi = getattr(adv, "rssi", None)
            is_band = any(k in name.lower() for k in ("band", "mi", "xiaomi", "huami"))
            items.append(
                {
                    "address": getattr(dev, "address", ""),
                    "name": name,
                    "rssi": rssi,
                    "is_band": is_band,
                }
            )
        items.sort(key=lambda item: (not item["is_band"], -(item["rssi"] or -999)))
        return {"duration": timeout, "devices": items}

    async def export_csv_now(self) -> dict[str, Any]:
        db_path = Path(self.output_dir) / DEFAULT_DB_FILENAME
        csv_dir = default_csv_dir(self.output_dir)
        exported = await asyncio.to_thread(export_database, db_path, csv_dir)
        return {
            "ok": True,
            "csv_dir": str(csv_dir),
            "tables": {
                table: {"path": str(path), "rows": rows}
                for table, (path, rows) in exported.items()
            },
        }
