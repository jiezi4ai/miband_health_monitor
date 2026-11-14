"""Best-effort Bluetooth SIG Battery Service (0x180F / 0x2A19) reader.

Mi Band 6 exposes proprietary battery reporting on some firmware revisions and
does not always implement the standard SIG Battery Level characteristic
``0x2A19``. This mixin probes ``0x2A19`` conservatively under ``_gatt_lock``,
caches an unsupported result for the client lifetime, and never fails the main
telemetry session if the characteristic is absent or temporarily unreadable.
"""

from __future__ import annotations

import logging
from typing import Optional

from .. import bluez
from .protocol import UUID_CHAR_BATTERY_LEVEL

logger = logging.getLogger("MiBand6Client")


def parse_battery_level(data: bytes | bytearray) -> int:
    """Decode one standard 1-byte Battery Level (0..100%) notification/read."""
    if not data:
        raise ValueError("Empty battery level payload")
    level = int(data[0])
    if not 0 <= level <= 100:
        raise ValueError(f"Battery level out of range [0..100]: {level}")
    return level


def _is_unsupported_error(exc: Exception) -> bool:
    """Return True when the BLE error means 0x2A19 does not exist on the device."""
    name = type(exc).__name__
    msg = str(exc).lower()
    return (
        "notfound" in name.lower()
        or "notsupported" in name.lower()
        or ("characteristic" in msg and "not found" in msg)
        or "not supported" in msg
        or "does not support" in msg
    )


class BatteryMixin:
    """Optional standard Battery Level (0x2A19) reader for MiBand6Client."""

    async def read_battery_level(self) -> Optional[int]:
        """Read current battery percentage (0..100) if supported, else None."""
        if self.client is None or getattr(self, "_battery_supported", None) is False:
            return None
        try:
            async with self._gatt_lock:
                if self.client is None:
                    return None
                raw = await self.client.read_gatt_char(UUID_CHAR_BATTERY_LEVEL)
        except Exception as exc:
            if _is_unsupported_error(exc):
                if getattr(self, "_battery_supported", None) is not False:
                    logger.info(
                        "Standard Battery Service (0x2A19) not supported by device; skipping future reads."
                    )
                self._battery_supported = False
            else:
                logger.debug(
                    "Best-effort battery read failed: %s",
                    bluez.describe_ble_error(exc),
                )
            return None

        if not raw:
            return None
        try:
            level = parse_battery_level(bytes(raw))
        except ValueError as exc:
            logger.debug("Ignoring invalid battery payload %r: %s", bytes(raw), exc)
            return None

        self._battery_supported = True
        self._last_battery_level = level
        return level
