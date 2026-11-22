"""Ask the band for arbitrary history types and print the raw start-date reply.

fetch_payload hides the metadata. The status byte in that reply is what tells
"the firmware knows this type, there is simply no data" apart from "the
firmware ignores the request": both produce an empty payload otherwise.

**One data-bearing type per session.** The band keeps a single fetch context: once
a type that *has* data is requested and not fetched, every later record type
answers ``0x02``. Probing ``0d 12 13`` in one session printed "rejected" for
0x12/0x13 even though both are accepted on their own -- a state artefact, not a
capability fact. This tool now stops after such a code instead of printing a
misleading table.

Usage:

    python tools/probe_fetch_types.py 48
    python tools/probe_fetch_types.py 12 13 38 3a 3d 49   # all empty: safe together

(after activating your venv: Linux .venv/bin/python, Windows .venv\\Scripts\\python.exe)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from miband_monitor.ble import (  # noqa: E402
    MiBand6Client,
    _env_device_id,
    is_placeholder_device_id,
)
from miband_monitor.config.defaults import (  # noqa: E402
    DEFAULT_HISTORY_DAYS,
    DEFAULT_SCAN_TIMEOUT,
    ENV_AUTH_KEY,
)
from miband_monitor.config.env import env_str, load_env  # noqa: E402
from miband_monitor.config.privacy import mask_address  # noqa: E402
from miband_monitor.history import (  # noqa: E402
    COMMAND_START_DATE,
    UUID_CHAR_ACTIVITY_DATA,
    UUID_CHAR_FETCH,
    BandHistoryFetcher,
    HistoryFetchError,
    encode_fetch_time,
)


async def probe(fetcher: BandHistoryFetcher, code: int, since: datetime) -> bool:
    """Print the reply for one type; returns True when it declared records.

    A True result means the band is now holding a fetch context for this type:
    any later record type in the same session will answer 0x02 for that reason
    alone, so the caller must stop.
    """
    declared = 0
    await fetcher._open()
    try:
        fetcher._drain()
        await fetcher._write(bytes([COMMAND_START_DATE, code & 0xFF]) + encode_fetch_time(since))
        metadata = await fetcher._next(fetcher._fetch_queue, "start-date response")
        print(f"  type {code:#04x}: reply {metadata.hex()}")
        if len(metadata) >= 7 and metadata[2] == 0x01:
            declared = int.from_bytes(metadata[3:7], "little")
            print(f"            accepted, declares {declared}")
        elif len(metadata) >= 3:
            print(f"            status 0x{metadata[2]:02x} (0x01 would be success)")
    finally:
        # Leave the characteristic in a clean state for the next probe.
        for uuid in (UUID_CHAR_FETCH, UUID_CHAR_ACTIVITY_DATA):
            try:
                await fetcher.client.stop_notify(uuid)
            except Exception:  # noqa: BLE001 - best effort
                pass
    return declared > 0


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Ask the band for arbitrary history types and print the start-date reply."
    )
    parser.add_argument(
        "codes", nargs="*", help="history type codes in hex, e.g. 48 2c 01"
    )
    parser.add_argument(
        "--scan-timeout",
        type=float,
        default=DEFAULT_SCAN_TIMEOUT,
        help="seconds to wait for the band's advertising pulse (default: %(default)s)",
    )
    parser.add_argument(
        "--reply-timeout",
        type=float,
        default=5.0,
        help=(
            "seconds to wait for one start-date reply (default: %(default)s). Keep it "
            "short when sweeping many codes: a code the firmware ignores simply stays "
            "silent, and the default 30 s would stretch a full 0x00-0xFF sweep to hours."
        ),
    )
    args = parser.parse_args(argv)
    codes = [int(item, 16) for item in args.codes] or [0x48]
    load_env()
    mac = _env_device_id()
    key = env_str(ENV_AUTH_KEY)
    if is_placeholder_device_id(mac) or not key:
        print("DEVICE_ID / AUTH_KEY missing from .env")
        return 2

    client = MiBand6Client(mac, key, scan_timeout=args.scan_timeout)
    print(f"Connecting to {mask_address(mac)} ...")
    await client.connect_and_authenticate()
    print("Authenticated.")
    fetcher = BandHistoryFetcher(client, timeout=args.reply_timeout)
    since = (datetime.now() - timedelta(days=DEFAULT_HISTORY_DAYS)).replace(
        second=0, microsecond=0
    )
    print(f"Asking for data since {since:%Y-%m-%d %H:%M}")
    try:
        for index, code in enumerate(codes):
            try:
                declared = await probe(fetcher, code, since)
            except HistoryFetchError as exc:
                print(f"  type {code:#04x}: {exc}")
                declared = False
            if declared and index + 1 < len(codes):
                print(
                    f"\n  STOP: {code:#04x} declared records and was not fetched, so the band is "
                    "now holding that fetch context.\n  Every later record type would answer 0x02 "
                    "for that reason alone.\n  Probe one data-bearing type per session."
                )
                return 3
            await asyncio.sleep(0.5)
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
