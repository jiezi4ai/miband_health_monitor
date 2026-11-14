"""Non-destructive diagnostic probe for Bluetooth SIG Battery Service (0x180F / 0x2A19).

Connects, authenticates, reads ``UUID_CHAR_BATTERY_LEVEL`` once and reports whether
the band firmware implements the standard battery characteristic or silently
ignores/omits it. Uses simulated band when invoked with ``--demo``.

Usage:

    ./.venv/bin/python tools/probe_battery.py
    ./.venv/bin/python tools/probe_battery.py --demo
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from miband_monitor.ble import (  # noqa: E402
    DEMO_AUTH_KEY_HEX,
    DEMO_DEVICE_ID,
    MiBand6Client,
    _env_device_id,
    is_placeholder_device_id,
)
from miband_monitor.config.defaults import ENV_AUTH_KEY  # noqa: E402
from miband_monitor.config.env import env_str, load_env  # noqa: E402
from miband_monitor.config.privacy import mask_address  # noqa: E402


async def probe_once(client: MiBand6Client) -> int:
    """Authenticate and attempt a single best-effort 0x2A19 battery read."""
    await client.connect_and_authenticate()
    try:
        level = await client.read_battery_level()
        if level is None:
            print("Battery 0x2A19 result: unsupported or unavailable on this firmware.")
            return 1
        print(f"Battery 0x2A19 result: {level}%")
        return 0
    finally:
        await client.disconnect()


async def main(argv: list[str]) -> int:
    if "--demo" in argv:
        from miband_monitor.ble.identity import normalize_auth_key
        from miband_monitor.simulator import FakeBleakScanner, SimulatedBand, simulated_factories

        band = SimulatedBand(auth_key=normalize_auth_key(DEMO_AUTH_KEY_HEX))
        sim_factory, _ = simulated_factories(band)

        class _DemoScanner(FakeBleakScanner):
            default_address = DEMO_DEVICE_ID

        client = MiBand6Client(
            DEMO_DEVICE_ID,
            DEMO_AUTH_KEY_HEX,
            client_factory=sim_factory,
            scanner_factory=_DemoScanner,
        )
        print("Probing simulated Mi Band 6 battery level (0x2A19)...")
        return await probe_once(client)

    load_env()
    mac = _env_device_id()
    key = env_str(ENV_AUTH_KEY)
    if is_placeholder_device_id(mac) or not key:
        print("DEVICE_ID / AUTH_KEY missing from .env (or pass --demo)")
        return 2

    client = MiBand6Client(mac, key)
    print(f"Connecting to {mask_address(mac)} ...")
    return await probe_once(client)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
