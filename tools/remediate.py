#!/usr/bin/env python3
"""Scripted diagnostic and remediation CLI backed by diagnostics.playbooks.

Usage::

    python tools/remediate.py --list
    python tools/remediate.py --diagnose
    python tools/remediate.py --run probe_radio_scan
    python tools/remediate.py --run clear_ghost_link --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from miband_monitor.ble.identity import _env_device_id  # noqa: E402
from miband_monitor.config.defaults import (  # noqa: E402
    DEFAULT_DATA_DIR,
    ENV_AUTH_KEY,
    ENV_DEVICE_NAME,
    ENV_OUTPUT_DIR,
)
from miband_monitor.config.env import load_env, secure_env_file  # noqa: E402
from miband_monitor.diagnostics import (  # noqa: E402
    get_playbook,
    list_playbooks,
    run_playbook,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run scripted BLE diagnostics and remediation playbooks."
    )
    parser.add_argument("--list", action="store_true", help="list all available playbooks")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="run doctor_check and print recommended remediation playbooks",
    )
    parser.add_argument("--run", metavar="PLAYBOOK_ID", help="execute a specific playbook")
    parser.add_argument(
        "--probe-seconds",
        type=float,
        default=15.0,
        help="listen duration for probe_radio_scan (default: 15s)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON output")
    return parser


def _print_result(result_dict: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result_dict, ensure_ascii=False, indent=2))
        return
    status = str(result_dict.get("status", "")).upper()
    print(f"[{status}] {result_dict.get('id')}: {result_dict.get('summary')}")
    for line in result_dict.get("details") or ():
        print(f"  - {line}")
    if result_dict.get("manual_command"):
        print(f"  Manual command: {result_dict['manual_command']}")
    if result_dict.get("recommended_next"):
        print(f"  Recommended next: {', '.join(result_dict['recommended_next'])}")


async def _async_main(args: argparse.Namespace) -> int:
    load_env()
    secure_env_file()
    device_id = _env_device_id()
    auth_key = (os.getenv(ENV_AUTH_KEY) or "").strip()
    output_dir = (os.getenv(ENV_OUTPUT_DIR) or DEFAULT_DATA_DIR).strip()
    device_name = (os.getenv(ENV_DEVICE_NAME) or "").strip() or None

    if args.list:
        specs = list_playbooks()
        if args.json:
            print(json.dumps(specs, ensure_ascii=False, indent=2))
        else:
            for spec in specs:
                tags = []
                if spec["requires_root"]:
                    tags.append("root/sudo")
                if spec["linux_only"]:
                    tags.append("linux")
                suffix = f" ({', '.join(tags)})" if tags else ""
                print(f"- {spec['id']}{suffix}: {spec['title']}")
                print(f"    {spec['summary']}")
        return 0

    if args.diagnose or not args.run:
        result = await run_playbook(
            "doctor_check",
            device_id=device_id,
            auth_key=auth_key,
            output_dir=output_dir,
            device_name=device_name,
        )
        _print_result(result.to_dict(), args.json)
        return 0 if result.ok else 1

    if get_playbook(args.run) is None:
        msg = {"error": f"unknown playbook {args.run!r}", "available": [p["id"] for p in list_playbooks()]}
        if args.json:
            print(json.dumps(msg, ensure_ascii=False))
        else:
            print(f"Error: unknown playbook {args.run!r}. Run --list to see available IDs.", file=sys.stderr)
        return 2

    result = await run_playbook(
        args.run,
        device_id=device_id,
        auth_key=auth_key,
        output_dir=output_dir,
        device_name=device_name,
        probe_duration=args.probe_seconds,
    )
    _print_result(result.to_dict(), args.json)
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
