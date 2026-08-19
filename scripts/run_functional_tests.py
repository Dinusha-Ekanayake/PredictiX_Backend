"""Run the functional suite and print the module-by-module result tables.

    python scripts/run_functional_tests.py              every module
    python scripts/run_functional_tests.py --module AU  one module
    python scripts/run_functional_tests.py --detail     show why a case failed
    python scripts/run_functional_tests.py --md         markdown, for the report

Each row carries the test-plan id, the case, the expected result and the
status observed against the live system. Exits non-zero if any case failed,
so CI can call it directly.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_here = Path(__file__).resolve()
_root = next(p for p in _here.parents if (p / "app" / "__init__.py").exists())
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

MODULES = [
    ("AU", "7.3.1  Authentication and Access Control"),
    ("UM", "7.3.2  User Management"),
    ("AS", "7.3.3  Asset Management"),
    ("PM", "7.3.4  Predictive Maintenance, Cost and Explainability"),
    ("TK", "7.3.5  Ticket Management and AI Processing"),
    ("DA", "7.3.6  Dashboard and Analytics"),
    ("RG", "7.3.7  Report Generation and RAG"),
    ("CB", "7.3.8  Agentic Chatbot"),
    ("NS", "7.3.9  Notifications, Profile and Settings"),
]

RESULTS = _root / "functional_results.json"


def run_pytest(module: str | None, quiet: bool) -> int:
    target = "app/tests/functional"
    if module:
        stem = {
            "AU": "test_au_authentication", "UM": "test_um_user_management",
            "AS": "test_as_asset_management", "PM": "test_pm_predictions",
            "TK": "test_tk_tickets", "DA": "test_da_dashboard",
            "RG": "test_rg_reports", "CB": "test_cb_chatbot",
            "NS": "test_ns_notifications",
        }.get(module.upper())
        if not stem:
            print(f"unknown module {module!r}; choose from {[m for m, _ in MODULES]}")
            raise SystemExit(2)
        target = f"app/tests/functional/{stem}.py"

    RESULTS.unlink(missing_ok=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-p", "no:cacheprovider",
         "-q" if quiet else "-v"],
        cwd=_root, text=True, encoding="utf-8", errors="replace",
        capture_output=quiet,
    )
    return proc.returncode


def load_rows() -> list[dict]:
    if not RESULTS.exists():
        return []
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def pad(s, n):
    s = str(s)
    return s[: n - 1] + "…" if len(s) > n else s.ljust(n)


def print_plain(rows: list[dict], detail: bool) -> dict:
    totals = {"PASS": 0, "FAIL": 0, "FRONTEND": 0, "SKIP": 0}
    by_prefix: dict[str, list[dict]] = {}
    for r in rows:
        by_prefix.setdefault(r["cid"].split("-")[0], []).append(r)

    for prefix, heading in MODULES:
        group = sorted(by_prefix.get(prefix, []), key=lambda r: r["cid"])
        if not group:
            continue
        print(f"\n{heading}")
        print("─" * 108)
        print(f"{pad('ID', 8)}{pad('Test Case', 44)}{pad('Expected Result', 44)}STATUS")
        print("─" * 108)
        for r in group:
            totals[r["status"]] = totals.get(r["status"], 0) + 1
            print(f"{pad(r['cid'], 8)}{pad(r['title'], 44)}"
                  f"{pad(r['expected'], 44)}{r['status']}")
            if detail and r["detail"]:
                print(f"        └─ {r['detail'][:150]}")
        p = sum(1 for r in group if r["status"] == "PASS")
        f = sum(1 for r in group if r["status"] == "FAIL")
        print("─" * 108)
        print(f"{len(group)} cases   {p} pass   {f} fail")
    return totals


def print_md(rows: list[dict]) -> dict:
    totals = {"PASS": 0, "FAIL": 0, "FRONTEND": 0, "SKIP": 0}
    by_prefix: dict[str, list[dict]] = {}
    for r in rows:
        by_prefix.setdefault(r["cid"].split("-")[0], []).append(r)

    for prefix, heading in MODULES:
        group = sorted(by_prefix.get(prefix, []), key=lambda r: r["cid"])
        if not group:
            continue
        print(f"\n### {heading}\n")
        print("| ID | Test Case | Expected Result | Status |")
        print("| --- | --- | --- | --- |")
        for r in group:
            totals[r["status"]] = totals.get(r["status"], 0) + 1
            status = {"PASS": "Pass", "FAIL": "**Fail**",
                      "FRONTEND": "Frontend", "SKIP": "Skipped"}[r["status"]]
            note = f" — {r['detail'][:90]}" if r["status"] == "FAIL" and r["detail"] else ""
            print(f"| {r['cid']} | {r['title']} | {r['expected']} | {status}{note} |")
    return totals


FIXTURE_TAG = "ZZFUNCTEST"

SWEEP = [
    ("tickets", "title LIKE '%ZZFUNCTEST%'"),
    ("notifications", "title LIKE 'Functional test%'"),
    ("assets", "asset_code LIKE 'ZZFUNCTEST%'"),
    ("profiles", "email LIKE 'zzfunctest%'"),
]


def sweep(apply: bool) -> int:
    """Remove rows an interrupted run left behind.

    Every case cleans up in a finally block, but a run killed mid-test (a
    dropped database connection, Ctrl-C) can still leave a row. Dry run by
    default so nothing is deleted without being shown first.
    """
    from sqlalchemy import text

    from app.db.session import SessionLocal

    total = 0
    with SessionLocal() as db:
        for table, where in SWEEP:
            rows = db.execute(text(f"SELECT count(*) FROM {table} WHERE {where}")).scalar()
            total += rows or 0
            print(f"  {table:<16}{rows}")
            if apply and rows:
                db.execute(text(f"DELETE FROM {table} WHERE {where}"))
        if apply:
            db.commit()

    if not total:
        print("\nNothing left behind.")
    elif apply:
        print(f"\nRemoved {total} row(s).")
    else:
        print(f"\n{total} row(s) would be removed. Re-run with --sweep-apply.")
        print("Note: a leftover profile also has a Supabase auth user, which "
              "this does not remove — delete those through DELETE /users/{id}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", help="one of AU UM AS PM TK DA RG CB NS")
    ap.add_argument("--detail", action="store_true", help="print the reason for each failure")
    ap.add_argument("--md", action="store_true", help="markdown tables")
    ap.add_argument("--verbose-pytest", action="store_true", help="stream pytest output")
    ap.add_argument("--sweep", action="store_true",
                    help="report rows an interrupted run left behind, without deleting")
    ap.add_argument("--sweep-apply", action="store_true",
                    help="actually delete what --sweep reports")
    args = ap.parse_args()

    if args.sweep or args.sweep_apply:
        return sweep(apply=args.sweep_apply)

    run_pytest(args.module, quiet=not args.verbose_pytest)
    rows = load_rows()

    if not rows:
        print("\nNo functional cases were recorded. Treating this as a failure.")
        print("The suite skips itself when DATABASE_URL is unset or the demo "
              "accounts are unavailable.")
        return 1

    totals = print_md(rows) if args.md else print_plain(rows, args.detail)

    total = sum(totals.values())
    print(f"\n{'═' * 108}")
    print(f"TOTAL {total} cases    {totals['PASS']} pass    {totals['FAIL']} fail"
          f"    {totals['FRONTEND']} frontend-only    {totals['SKIP']} skipped")
    if totals["FAIL"]:
        print("\nFailing cases:")
        for r in sorted(rows, key=lambda r: r["cid"]):
            if r["status"] == "FAIL":
                print(f"  {r['cid']}  {r['title']}")
                print(f"        {r['detail'][:160]}")
    print("═" * 108)
    return 1 if totals["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
