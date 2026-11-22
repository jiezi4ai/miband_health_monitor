#!/usr/bin/env python3
"""Fail when documentation test-count claims drift from the collected suite.

Documentation numbers go stale after every refactor, so this gate compares the
claims against the real collected test count (improvement plan R-1):

* lower bounds ("NNN+ tests" / "NNN+ unit" / "NNN+ 单元") must not exceed the
  collected count;
* exact claims ("NNN passed") must stay within 10% of it, otherwise the line
  should be rewritten as a lower bound.

Only the two known drift spots are scanned: the top-level READMEs and the
cross-platform guides. testing.md keeps explicitly historical baselines
("pre-refactor" / "重构前") on purpose and is out of scope.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Documentation files whose test-count claims are checked.
SCANNED_FILES = [
    "README.md",
    "README.zh-CN.md",
    "docs/guides/cross-platform.md",
    "docs/guides/cross-platform.zh-CN.md",
]

LOWER_BOUND_RE = re.compile(r"\b(\d{2,4})\s*\+\s*(?:unit|tests?\b|单元)")
EXACT_RE = re.compile(r"\b(\d{3,4})\s+passed\b")
#: Exact claims older than this fraction of the suite are stale.
EXACT_TOLERANCE = 0.10


def collected_count() -> int:
    """Run pytest --collect-only and return the number of collected tests."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    match = re.search(r"(\d+)\s+tests?\s+collected", proc.stdout)
    if match is None:
        print("FAIL could not parse `pytest --collect-only` output")
        print(proc.stdout[-400:])
        return -1
    return int(match.group(1))


def scan_file(rel_path: str, total: int) -> tuple[list[str], int]:
    """Return (violations, claims_checked) for one documentation file."""
    violations: list[str] = []
    checked = 0
    path = ROOT / rel_path
    text = path.read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        for match in LOWER_BOUND_RE.finditer(line):
            claim = int(match.group(1))
            checked += 1
            if claim > total:
                violations.append(
                    f"{rel_path}:{number}: lower bound {claim}+ exceeds collected {total}"
                )
        for match in EXACT_RE.finditer(line):
            claim = int(match.group(1))
            checked += 1
            if abs(total - claim) > EXACT_TOLERANCE * total:
                violations.append(
                    f"{rel_path}:{number}: exact claim '{claim} passed' is >10% "
                    f"from collected {total}; rewrite as a lower bound (NNN+ tests)"
                )
    return violations, checked


def main(argv: list[str] | None = None) -> int:
    """Check every claim and return a non-zero status on violation."""
    total = collected_count()
    if total < 0:
        return 1
    print(f"collected {total} tests")

    all_violations: list[str] = []
    checked_total = 0
    for rel_path in SCANNED_FILES:
        if not (ROOT / rel_path).is_file():
            all_violations.append(f"{rel_path}: scanned file is missing")
            continue
        violations, checked = scan_file(rel_path, total)
        all_violations.extend(violations)
        checked_total += checked

    print(f"checked {checked_total} test-count claim(s) in {len(SCANNED_FILES)} file(s)")
    for item in all_violations:
        print(f"FAIL {item}")
    if all_violations:
        print(f"{len(all_violations)} stale test-count claim(s); update the docs or the suite")
        return 1
    print("OK: documentation test-count claims are within tolerance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
