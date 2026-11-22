"""CLI flags for the optional downlink clock sync (B-10).

Kept outside ``args.py`` so the parser module stays under the 300-line budget,
following the example of ``backup_cli.add_backup_args``.
"""

from __future__ import annotations

import argparse


def add_time_args(parser: argparse.ArgumentParser) -> None:
    """Add the mutually exclusive time-sync flags to *parser*."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--sync-time",
        action="store_true",
        help=(
            "write the host clock to the band over the standard Current Time "
            "characteristic (0x2A2B) after authentication; failure never aborts "
            "the session"
        ),
    )
    group.add_argument(
        "--sync-time-dry-run",
        action="store_true",
        help="read the band clock and log the drift without writing (safe first check)",
    )


def time_sync_mode(args: argparse.Namespace) -> str | None:
    """Return ``"apply"``, ``"dry-run"`` or ``None`` from parsed args."""
    if getattr(args, "sync_time", False):
        return "apply"
    if getattr(args, "sync_time_dry_run", False):
        return "dry-run"
    return None


__all__ = ["add_time_args", "time_sync_mode"]
