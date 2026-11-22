#!/usr/bin/env python3
"""Back up the telemetry SQLite database with online-copy + verification.

Usage (from repo root, after activating the venv)::

    python tools/backup_db.py --db data/mi_band.db --backup data/backups
    python tools/backup_db.py --db data/mi_band.db --backup data/snapshots/mi_band.db
    python tools/backup_db.py --verify data/mi_band.db data/backups/mi_band-20261120-080000.db

A directory target creates a timestamped snapshot and keeps ``--keep`` copies
(default 5). An explicit ``*.db`` target is a single verified copy with no
rotation. The backup uses SQLite's online backup API (WAL-safe) and is verified
with ``PRAGMA integrity_check`` plus per-table row counts before success.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from miband_monitor.storage import (  # noqa: E402
    DEFAULT_KEEP,
    backup_database,
    summarize_counts,
    verify_backup,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safe, verified SQLite backup.")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="create a backup (default)")
    run.add_argument("--db", default="data/mi_band.db", help="source database")
    run.add_argument("--backup", required=True, help="destination dir or .db file")
    run.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="snapshots to keep (dir mode)")

    verify = sub.add_parser("verify", help="verify an existing backup against its source")
    verify.add_argument("source", help="source database")
    verify.add_argument("backup", help="backup database to verify")

    args = parser.parse_args(argv)
    command = args.command or "run"
    if command == "verify":
        try:
            counts = verify_backup(Path(args.source), Path(args.backup))
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 1
        print(f"[OK] backup verified: {summarize_counts(counts)}")
        return 0

    # run
    try:
        result = backup_database(Path(args.db), Path(args.backup), keep=args.keep)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(f"[OK] backup written -> {result['path']}")
    print(f"     {summarize_counts(result['counts'])}")
    for stale in result["rotated"]:
        print(f"     rotated out: {stale.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
