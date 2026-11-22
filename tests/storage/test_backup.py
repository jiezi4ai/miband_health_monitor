"""B-11: verified whole-database backup with rotation."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from miband_monitor.storage import (
    DEFAULT_KEEP,
    backup_database,
    verify_backup,
)

ROOT = Path(__file__).resolve().parents[2]


def _make_db(path: Path, rows: int = 3) -> None:
    from miband_monitor.storage.sqlite import open_database

    conn = open_database(path)
    try:
        for i in range(rows):
            conn.execute(
                "INSERT INTO heart_rate (ts, iso_time, bpm) VALUES (?, ?, ?)",
                (1000.0 + i, f"1970-01-01T00:{i:02d}:00+00:00", 70 + i),
            )
        conn.commit()
    finally:
        conn.close()


def test_backup_to_explicit_file_is_verified(tmp_path):
    src = tmp_path / "mi_band.db"
    dst = tmp_path / "copy.db"
    _make_db(src, rows=4)

    result = backup_database(src, dst)
    assert result["path"] == dst
    assert result["counts"]["heart_rate"] == 4
    assert result["rotated"] == []
    assert verify_backup(src, dst)["heart_rate"] == 4

    # The copy is independently openable and holds the rows.
    conn = sqlite3.connect(dst)
    try:
        assert conn.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0] == 4
    finally:
        conn.close()


def test_backup_to_dir_rotates_and_keeps_n(tmp_path):
    src = tmp_path / "mi_band.db"
    _make_db(src, rows=2)
    dest = tmp_path / "backups"

    for _ in range(3):
        backup_database(src, dest, keep=2)

    snapshots = sorted(dest.glob("mi_band-*.db"))
    assert len(snapshots) == 2  # kept only the newest two
    for snapshot in snapshots:
        assert verify_backup(src, snapshot)["heart_rate"] == 2


def test_verify_rejects_tampered_backup(tmp_path):
    src = tmp_path / "mi_band.db"
    dst = tmp_path / "bad.db"
    _make_db(src, rows=3)
    backup_database(src, dst)

    conn = sqlite3.connect(dst)
    try:
        conn.execute("DELETE FROM heart_rate")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="differ"):
        verify_backup(src, dst)


def test_backup_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "missing.db", tmp_path / "out.db")


def test_backup_db_tool_cli_roundtrip(tmp_path):
    src = tmp_path / "mi_band.db"
    dst = tmp_path / "snapshot.db"
    _make_db(src, rows=5)

    run = subprocess.run(
        [sys.executable, "tools/backup_db.py", "run", "--db", str(src), "--backup", str(dst)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr
    assert "backup written" in run.stdout

    verify = subprocess.run(
        [sys.executable, "tools/backup_db.py", "verify", str(src), str(dst)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert verify.returncode == 0, verify.stderr
    assert "backup verified" in verify.stdout


def test_default_keep_is_sane():
    assert DEFAULT_KEEP >= 1


def test_cli_backup_flag_runs_after_demo_session(tmp_path):
    """`--backup PATH` is wired into the main CLI and produces a verified copy."""
    import asyncio

    import miband_monitor.cli.app as cli_app

    out_dir = tmp_path / "out"
    backup_path = tmp_path / "backup.db"
    code = asyncio.run(
        cli_app.main(
            [
                "--demo", "1",
                "--storage", "sqlite",
                "--output", str(out_dir),
                "--backup", str(backup_path),
            ]
        )
    )
    assert code == 0
    assert backup_path.is_file()
    assert verify_backup(out_dir / "mi_band.db", backup_path)["heart_rate"] >= 0

