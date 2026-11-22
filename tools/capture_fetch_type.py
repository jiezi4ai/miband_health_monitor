"""Dump the raw bytes of one band-side history type, without acknowledging them.

The normal fetch path ends with an ACK, which makes the band drop what it just
sent. That is correct once a parser is trusted, but useless while a layout is
still unknown: a bad guess would leave nothing to re-read. This tool reads the
same stream and stops before the ACK, so the records stay on the band and the
capture can be repeated as often as needed.

Usage:

    python tools/capture_fetch_type.py 0d --days 7
    python tools/capture_fetch_type.py 0d --days 30 --out data/pai_raw.jsonl

The output is one JSON line per capture: the start-date header, the completion
header, the declared length and the payload as hex.
"""

from __future__ import annotations

import argparse
import asyncio
import json
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
    COMMAND_FETCH_DATA,
    COMMAND_START_DATE,
    BandHistoryFetcher,
    HistoryFetchError,
    encode_fetch_time,
)


async def capture(fetcher: BandHistoryFetcher, code: int, since: datetime) -> dict:
    await fetcher._open()
    try:
        fetcher._drain()
        await fetcher._write(bytes([COMMAND_START_DATE, code & 0xFF]) + encode_fetch_time(since))
        header = await fetcher._next(fetcher._fetch_queue, "start-date response")
        print(f"  header      {header.hex()}")
        if len(header) < 7 or header[2] != 0x01:
            raise HistoryFetchError(f"band rejected type {code:#04x}: {header.hex()}")
        declared = int.from_bytes(header[3:7], "little")
        print(f"  declared    {declared}")
        if not declared:
            return {"type": code, "declared": 0, "header": header.hex()}

        await fetcher._write(bytes([COMMAND_FETCH_DATA]))
        raw, completion = await fetcher._collect(declared)
        print(f"  completion  {completion.hex()}")
        print(f"  payload     {len(raw)} bytes")
        # Deliberately no ACK: the band keeps the records for the next capture.
        return {
            "type": code,
            "declared": declared,
            "header": header.hex(),
            "completion": completion.hex(),
            "payload": raw.hex(),
            "since": since.isoformat(),
            "captured_at": datetime.now().isoformat(timespec="seconds"),
        }
    finally:
        await fetcher._close()


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Dump one history type's raw bytes without ACK.")
    parser.add_argument("code", help="history type in hex, e.g. 0d")
    parser.add_argument("--days", type=int, default=DEFAULT_HISTORY_DAYS,
                        help="how far back to ask for (default: %(default)s)")
    parser.add_argument("--out", default=None, help="JSONL file to append the capture to")
    parser.add_argument("--scan-timeout", type=float, default=DEFAULT_SCAN_TIMEOUT)
    args = parser.parse_args(argv)

    code = int(args.code, 16)
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
    fetcher = BandHistoryFetcher(client)
    since = (datetime.now() - timedelta(days=args.days)).replace(second=0, microsecond=0)
    print(f"Asking for type {code:#04x} since {since:%Y-%m-%d %H:%M}")
    try:
        record = await capture(fetcher, code, since)
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001 - best effort
            pass

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(f"  saved to    {path}")

    size = len(record.get("payload", "")) // 2
    print(f"\npayload {size} bytes; NOT acked, band copy intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
