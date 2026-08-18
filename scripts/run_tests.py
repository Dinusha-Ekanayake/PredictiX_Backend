"""Run the test suite and print a per-group pass/fail summary.

    python scripts/run_tests.py           # everything
    python scripts/run_tests.py --unit    # no database needed
    python scripts/run_tests.py --cov     # with a coverage report

Unit tests run against mocks and need nothing external. Integration tests need
DATABASE_URL to point at a database with the demo accounts seeded, and are
skipped automatically when it is not set.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GROUPS = [
    ("Unit: shared logic", "app/tests/unit", False),
    ("Router: mocked DB", "app/tests/qa_automated", False),
    ("Integration: live API + data", "app/tests/integration", True),
]

SUMMARY = re.compile(r"(\d+) (passed|failed|skipped|error)")


def run(path: str, extra: list[str]) -> tuple[dict, int]:
    # No -q here: pytest.ini already sets it, and a second one suppresses the
    # summary line this function parses.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", path, "--no-header",
         "-p", "no:cacheprovider", *extra],
        cwd=ROOT, capture_output=True, text=True,
    )
    tail = (proc.stdout or "") + (proc.stderr or "")
    counts = {kind: int(n) for n, kind in SUMMARY.findall(tail)}
    return counts, proc.returncode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", action="store_true", help="skip integration tests")
    ap.add_argument("--cov", action="store_true", help="add a coverage report")
    args = ap.parse_args()

    extra = ["--cov=app", "--cov-report=term-missing:skip-covered"] if args.cov else []

    print(f"{'GROUP':<32}{'PASS':>6}{'FAIL':>6}{'SKIP':>6}   STATUS")
    print("-" * 66)

    totals = {"passed": 0, "failed": 0, "skipped": 0}
    worst = 0

    for label, path, needs_db in GROUPS:
        if needs_db and args.unit:
            print(f"{label:<32}{'-':>6}{'-':>6}{'-':>6}   SKIPPED (--unit)")
            continue
        counts, code = run(path, extra)
        for k in totals:
            totals[k] += counts.get(k, 0)
        failed = counts.get("failed", 0) + counts.get("error", 0)
        # pytest exits 5 when a group collected nothing; that is not a failure.
        status = "PASS" if failed == 0 and code in (0, 5) else "FAIL"
        worst = max(worst, 0 if status == "PASS" else 1)
        print(f"{label:<32}{counts.get('passed', 0):>6}{failed:>6}"
              f"{counts.get('skipped', 0):>6}   {status}")

    print("-" * 66)
    print(f"{'TOTAL':<32}{totals['passed']:>6}{totals['failed']:>6}{totals['skipped']:>6}"
          f"   {'ALL PASSING' if worst == 0 else 'FAILURES PRESENT'}")

    sys.exit(worst)


if __name__ == "__main__":
    main()
