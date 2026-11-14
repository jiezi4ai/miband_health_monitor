"""Demo runner backed by the in-memory Mi Band 6 simulator."""

from __future__ import annotations

import logging
from typing import Optional

from ..ble.client import MiBand6Client, StreamCallbacks
from ..ble.identity import normalize_auth_key
from ..config.defaults import (
    DEFAULT_BATTERY_POLL_SECONDS,
    DEFAULT_HR_SILENCE_HARD_SECONDS,
    DEFAULT_HR_SILENCE_SOFT_SECONDS,
)
from ..dashboard import TelemetryHub
from ..workout import WorkoutSession
from .runner import run_monitor

logger = logging.getLogger("MiBand6Client")


async def run_demo(
    device_id: str,
    auth_key_hex: str,
    *,
    duration: Optional[int] = None,
    imu: bool = False,
    callbacks: Optional[StreamCallbacks] = None,
    sync_history_days: Optional[int] = None,
    sync_sleep_spo2: bool = False,
    band_tz: Optional[str] = None,
    mtu: Optional[int] = None,
    hr_silence_soft: float = DEFAULT_HR_SILENCE_SOFT_SECONDS,
    hr_silence_hard: float = DEFAULT_HR_SILENCE_HARD_SECONDS,
    workout: Optional[WorkoutSession] = None,
    hub: Optional[TelemetryHub] = None,
    battery_interval: float = DEFAULT_BATTERY_POLL_SECONDS,
) -> None:
    """Run the full client stack against the in-memory simulator (no hardware)."""
    from ..simulator import FakeBleakScanner, SimulatedBand, simulated_factories

    band = SimulatedBand(
        auth_key=normalize_auth_key(auth_key_hex),
        continuous_interval=0.8 if workout is not None else None,
    )
    sim_client_factory, _scanner_factory = simulated_factories(band)

    class _DemoScanner(FakeBleakScanner):
        default_address = device_id

    def _factory(mac: str, key: str) -> MiBand6Client:
        return MiBand6Client(
            mac,
            key,
            mtu=mtu,
            client_factory=sim_client_factory,
            scanner_factory=_DemoScanner,
            hr_silence_soft_seconds=hr_silence_soft,
            hr_silence_hard_seconds=hr_silence_hard,
        )

    logger.info("DEMO MODE: using an in-memory simulated Mi Band 6 (no Bluetooth needed).")
    await run_monitor(
        device_id,
        auth_key_hex,
        duration=duration,
        imu=imu,
        callbacks=callbacks,
        scan_timeout=10.0,
        reconnect=True,
        reconnect_initial_delay=0.2,
        reconnect_max_delay=1.0,
        sync_history_days=sync_history_days,
        sync_sleep_spo2=sync_sleep_spo2,
        band_tz=band_tz,
        mtu=mtu,
        hr_silence_soft=hr_silence_soft,
        hr_silence_hard=hr_silence_hard,
        workout=workout,
        hub=hub,
        battery_interval=battery_interval,
        client_factory=_factory,
    )
