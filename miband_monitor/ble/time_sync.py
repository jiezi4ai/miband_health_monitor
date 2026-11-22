"""Downlink time synchronisation over the standard Current Time characteristic.

Gadgetbridge's ``HuamiSupport.setCurrentTime()`` writes the Bluetooth SIG
``Current Time`` characteristic (``0x2A2B``) using a Mi-Band-specific 11-byte
variant of the standard 10-byte record: a trailing UTC-offset byte in quarter
hours is appended.  The layout is implemented here from the protocol facts in
that implementation (AGPL-3.0, no code copied).

The band timestamps every history record with its own clock, so a drifting band
silently skews minute alignment.  This mixin stays best-effort: an absent
characteristic or a failed write returns a diagnostic dict and never aborts the
telemetry session.
"""

from __future__ import annotations

import logging
import struct
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger("MiBand6Client")

#: Bluetooth SIG Current Time (read + write).
UUID_CHAR_CURRENT_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"


def resolve_timezone(spec: Optional[str | tzinfo] = None) -> tzinfo:
    """Resolve an explicit tzinfo/IANA name, falling back to host local time."""
    if isinstance(spec, tzinfo):
        return spec
    raw = (spec or "").strip()
    if not raw:
        return datetime.now().astimezone().tzinfo or timezone.utc
    if raw.upper() in ("UTC", "Z"):
        return timezone.utc
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone {raw!r}") from exc


def _day_of_week(moment: datetime) -> int:
    """SIG day-of-week: Monday=1 ... Saturday=6, Sunday=7."""
    return (moment.isoweekday() % 7) or 7


def _tz_quarters(moment: datetime) -> int:
    offset = moment.utcoffset() or timedelta(0)
    return max(-128, min(127, int(offset.total_seconds() // 900)))


def encode_current_time(
    moment: datetime, *, tz: Optional[str | tzinfo] = None
) -> bytes:
    """Encode the Mi Band 11-byte Current Time record.

    ``year LE16, month, day, hour, minute, second, day_of_week, fractions256,
    adjust_reason, utc_offset_quarters``.  ``fractions256`` and
    ``adjust_reason`` are zero; the trailing offset byte is the Mi Band
    extension (the standard record stops after ``adjust_reason``).
    """
    zone = resolve_timezone(tz)
    local = moment.astimezone(zone) if moment.tzinfo else moment.replace(tzinfo=zone)
    head = struct.pack(
        "<HBBBBBBBB",
        local.year,
        local.month,
        local.day,
        local.hour,
        local.minute,
        local.second,
        _day_of_week(local),
        0,  # fractions256
        0,  # adjust reason
    )
    return head + bytes([_tz_quarters(local) & 0xFF])


def decode_current_time(raw: bytes) -> Optional[datetime]:
    """Decode a Current Time read; ``None`` when it is obviously invalid."""
    if len(raw) < 9:
        return None
    year, month, day, hour, minute, second, _dow, _frac, _reason = struct.unpack_from(
        "<HBBBBBBBB", raw, 0
    )
    if year < 2000:
        return None
    if len(raw) >= 11:
        quarters = struct.unpack_from("<b", raw, 10)[0]
        zone: tzinfo = timezone(timedelta(minutes=quarters * 15))
    else:
        zone = resolve_timezone()
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=zone)
    except ValueError:
        return None


def _drift_seconds(host: datetime, band: Optional[datetime]) -> Optional[float]:
    if band is None:
        return None
    return round(host.timestamp() - band.timestamp(), 1)


class TimeSyncMixin:
    """Best-effort Current Time reader/writer for MiBand6Client."""

    async def read_current_time(self) -> Optional[datetime]:
        """Read the band clock, or ``None`` when unsupported/unreadable."""
        if getattr(self, "client", None) is None:
            return None
        try:
            async with self._gatt_lock:
                raw = await self.client.read_gatt_char(UUID_CHAR_CURRENT_TIME)
        except Exception as exc:
            logger.debug("Current Time read failed: %s", exc)
            return None
        return decode_current_time(bytes(raw or b""))

    async def sync_current_time(
        self,
        *,
        dry_run: bool = False,
        tz: Optional[str | tzinfo] = None,
    ) -> dict[str, Any]:
        """Optionally write the host clock to the band and report the drift.

        Returns a diagnostic dict instead of raising: ``supported``,
        ``before``/``after`` (ISO strings), ``drift_seconds``, ``wrote`` and
        ``error``.  ``dry_run`` only reads, so it is safe to run on a first
        real-device check.
        """
        host = datetime.now(resolve_timezone(tz))
        before = await self.read_current_time()
        result: dict[str, Any] = {
            "supported": before is not None,
            "before": before.isoformat() if before else None,
            "drift_seconds": _drift_seconds(host, before),
            "wrote": False,
            "dry_run": bool(dry_run),
            "error": None,
        }
        if dry_run:
            return result
        if getattr(self, "client", None) is None:
            result["error"] = "not connected"
            return result

        payload = encode_current_time(host, tz=tz)
        for with_response in (True, False):
            try:
                async with self._gatt_lock:
                    await self.client.write_gatt_char(
                        UUID_CHAR_CURRENT_TIME, payload, response=with_response
                    )
                result["wrote"] = True
                break
            except Exception as exc:
                result["error"] = str(exc)
                logger.debug(
                    "Current Time write (response=%s) failed: %s", with_response, exc
                )
        if result["wrote"]:
            after = await self.read_current_time()
            result["after"] = after.isoformat() if after else None
            result["error"] = None
        return result


async def maybe_sync_time(client, *, dry_run: bool, tz: Optional[str | tzinfo] = None) -> dict:
    """Run :meth:`sync_current_time` when the client supports it (runner hook)."""
    sync = getattr(client, "sync_current_time", None)
    if not callable(sync):
        return {"supported": False, "error": "client has no time-sync support"}
    result = await sync(dry_run=dry_run, tz=tz)
    if result.get("wrote"):
        logger.info(
            "Band clock aligned (drift was %ss).", result.get("drift_seconds")
        )
    elif result.get("dry_run"):
        logger.info(
            "Band clock drift %ss (dry-run; nothing written).", result.get("drift_seconds")
        )
    else:
        logger.warning("Band time sync skipped: %s", result.get("error") or "unsupported")
    return result


__all__ = [
    "UUID_CHAR_CURRENT_TIME",
    "TimeSyncMixin",
    "decode_current_time",
    "encode_current_time",
    "maybe_sync_time",
    "resolve_timezone",
]
