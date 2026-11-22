"""Safe whole-database backup for the telemetry SQLite store (B-11).

A WAL-mode database must not be copied with ``shutil.copy``: the committed rows
can still live in the ``-wal`` sidecar, so a raw file copy may be missing the
latest data or be internally inconsistent. This module uses SQLite's online
backup API (``Connection.backup``), which produces a consistent snapshot while
the source stays open, then **verifies** it with ``PRAGMA integrity_check`` and
per-table row counts before considering the backup valid.

Rotation keeps the N most recent timestamped snapshots; an explicit ``.db``
target is written exactly once with no rotation. All files are created through
the project's 0600/0700 permission helpers.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..config.security import secure_directory, secure_file
from .schema import TABLE_COLUMNS

logger = logging.getLogger("MiBandBackup")

#: Default number of timestamped snapshots to keep when backing up to a dir.
DEFAULT_KEEP = 5

#: Prefix for timestamped snapshot filenames (used for both creation + rotation).
SNAPSHOT_PREFIX = "mi_band-"
SNAPSHOT_SUFFIX = ".db"


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in TABLE_COLUMNS:
        counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return counts


def verify_backup(source: Path, backup: Path) -> dict[str, int]:
    """Verify *backup* is a consistent copy of *source*.

    Returns the per-table row counts on success. Raises ``RuntimeError`` when
    integrity check fails or counts diverge, so a partial copy is never treated
    as a usable backup.
    """
    for path in (source, backup):
        if not path.is_file():
            raise FileNotFoundError(f"database not found: {path}")

    src = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    dst = sqlite3.connect(f"file:{backup.resolve()}?mode=ro", uri=True)
    try:
        integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"backup failed integrity_check: {integrity}")
        src_counts = _table_counts(src)
        dst_counts = _table_counts(dst)
        if src_counts != dst_counts:
            raise RuntimeError(
                f"backup row counts differ from source: {dst_counts} != {src_counts}"
            )
        return dst_counts
    finally:
        src.close()
        dst.close()


def _resolve_destination(dest: Path) -> tuple[Path, bool]:
    """Return (target_path, rotate). Directory/no-suffix => timestamped + rotate."""
    if dest.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
        return dest, False
    # Treat as a directory (create it) and generate a timestamped filename.
    # Microseconds keep two rapid backups (e.g. a tight retry loop) distinct.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return dest / f"{SNAPSHOT_PREFIX}{stamp}{SNAPSHOT_SUFFIX}", True


def _rotate(dest_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest *keep* timestamped snapshots. Returns removed."""
    if keep < 1:
        return []
    snapshots = sorted(
        dest_dir.glob(f"{SNAPSHOT_PREFIX}*{SNAPSHOT_SUFFIX}"),
        key=lambda p: p.stat().st_mtime_ns,
    )
    removed: list[Path] = []
    for stale in snapshots[:-keep]:
        stale.unlink()
        removed.append(stale)
    return removed


def backup_database(source: Path, dest: Path, *, keep: int = DEFAULT_KEEP) -> dict:
    """Create a verified whole-database backup at *dest*.

    ``dest`` may be a directory (timestamped snapshot + rotation, keeping
    ``keep`` copies) or an explicit ``*.db`` file (single copy, no rotation).
    Returns a summary dict with ``path``, ``counts`` and ``rotated``.
    """
    source = Path(source)
    dest = Path(dest)
    if not source.is_file():
        raise FileNotFoundError(f"source database not found: {source}")

    target, rotate = _resolve_destination(dest)
    secure_directory(target.parent)

    src = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)  # consistent snapshot, WAL-safe
    finally:
        src.close()
        dst.close()
    secure_file(target)

    counts = verify_backup(source, target)
    removed = _rotate(target.parent, keep) if rotate else []
    logger.info("Backup verified: %s (%s)", target, summarize_counts(counts))
    return {"path": target, "counts": counts, "rotated": removed}


def summarize_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{name}={n}" for name, n in sorted(counts.items()))
