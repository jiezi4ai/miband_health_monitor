"""Command-line entry point for the single-file offline dashboard.

``build()`` collects the payload, renders the HTML and writes it with private
POSIX permissions; ``main()`` is the historical CLI (same flags, same output).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Optional, Sequence

from miband_monitor.config.defaults import DEFAULT_OFFLINE_DAYS
from miband_monitor.config.security import secure_directory, secure_file

from .collect import collect
from .ranges import RANGE_CHOICES, RANGE_LABELS, normalize_range
from .render import render
from .strings import CLI_ERROR, CLI_RANGE, CLI_SUMMARY, CLI_WROTE


def build(
    db_path: str | Path,
    output: str | Path,
    *,
    days: int = DEFAULT_OFFLINE_DAYS,
    spo2_sleep_path: str | Path | None = None,
    range: Optional[str] = None,
    kpi_range: Optional[str] = None,
) -> Path:
    payload = collect(
        db_path, days=days, spo2_sleep_path=spo2_sleep_path,
        range=range, kpi_range=kpi_range,
    )
    html = render(payload)
    target = Path(output)
    # ``--output data/reports/dash.html`` is a natural thing to type; don't make
    # the user mkdir first.
    secure_directory(target.parent)
    target.write_text(html, encoding="utf-8")
    secure_file(target)
    return target


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a self-contained historical health dashboard (HTML)."
    )
    parser.add_argument("--db", required=True, help="path to mi_band.db")
    parser.add_argument("-o", "--output", default="history_dashboard.html", help="output HTML file")
    parser.add_argument(
        "--days", type=int, default=DEFAULT_OFFLINE_DAYS,
        help=f"window in days (default {DEFAULT_OFFLINE_DAYS})",
    )
    parser.add_argument(
        "--range", choices=RANGE_CHOICES, default=None,
        help="semantic window: day / week / month / all (overrides --days)",
    )
    parser.add_argument(
        "--kpi-range", choices=RANGE_CHOICES, default=None,
        help="KPI aggregation range (default: follows --range, else day)",
    )
    parser.add_argument(
        "--spo2-sleep-jsonl",
        default=None,
        help=(
            "explicit path to spo2_sleep.jsonl; by default the file next to "
            "--db is used, and the dedicated spo2_sleep SQLite table wins"
        ),
    )
    args = parser.parse_args(argv)
    try:
        normalize_range(args.range)
        normalize_range(args.kpi_range)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        target = build(
            args.db, args.output, days=args.days,
            spo2_sleep_path=args.spo2_sleep_jsonl,
            range=args.range, kpi_range=args.kpi_range,
        )
        payload = collect(
            args.db, days=args.days, spo2_sleep_path=args.spo2_sleep_jsonl,
            range=args.range, kpi_range=args.kpi_range,
        )
    except (FileNotFoundError, sqlite3.Error) as exc:
        print(CLI_ERROR.format(message=exc), file=sys.stderr)
        return 1

    print(CLI_WROTE.format(target=target, size=target.stat().st_size // 1024))
    print(
        CLI_RANGE.format(
            range=payload["meta"]["range_label"],
            kpi=RANGE_LABELS.get(payload["meta"]["kpi_range"], payload["meta"]["kpi_range"]),
        )
    )
    print(
        CLI_SUMMARY.format(
            activity=payload["meta"]["activity_samples"],
            sessions=len(payload["sleep"]["sessions"]),
            spo2=payload["meta"]["spo2_samples"],
            spo2_sleep=payload["meta"]["spo2_sleep_samples"],
            source=payload["meta"]["spo2_sleep_source"],
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
