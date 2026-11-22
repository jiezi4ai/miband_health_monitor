"""Shared CLI wiring for the post-session database backup (B-11).

Kept separate so cli/args.py and cli/app.py stay under the 300-line budget.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ..storage.backup import backup_database


def add_backup_args(parser: argparse.ArgumentParser) -> None:
    """Register the ``--backup`` / ``--backup-keep`` flags."""
    parser.add_argument(
        "--backup", metavar="PATH", default=None,
        help="back up mi_band.db after session: dir=timestamped snapshots, *.db=single copy",
    )
    parser.add_argument(
        "--backup-keep", type=int, default=5,
        help="snapshots to keep when --backup is a directory (default: 5)",
    )


def maybe_backup(args: argparse.Namespace, db_path: Path, logger: logging.Logger) -> bool:
    """Run the requested post-session backup. Returns True only on verified success.

    Logs and swallows its own errors so the caller needs a single boolean check;
    returns False when the flag was not set or storage is not SQLite.
    """
    if not getattr(args, "backup", None):
        return False
    if args.storage not in ("sqlite", "both"):
        logger.warning("--backup requires --storage sqlite or both (current: %s)", args.storage)
        return False
    try:
        result = backup_database(db_path, Path(args.backup), keep=args.backup_keep)
    except Exception as exc:  # noqa: BLE001 - backup must never abort the session
        logger.error("Backup failed: %s", exc)
        return False
    counts = ", ".join(f"{k}={v}" for k, v in sorted(result["counts"].items()))
    logger.info("Backup verified -> %s (%s)", result["path"], counts)
    return True
