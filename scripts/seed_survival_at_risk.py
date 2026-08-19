"""Bring a set of assets inside the survival model's 7 and 30 day horizons.

The warehouse survival page scores the 25 lowest-health assets per warehouse and
buckets each one by its soonest component's median predicted life. With the
fleet as generated, no asset falls inside 7 days and only a handful inside 30,
so those charts render empty.

This degrades the latest sensor reading of assets already inside each
warehouse's cohort until their oil life lands in the requested window.

Only two columns change, both on an existing row:

    sensor_readings.oil_life_pct
    sensor_readings.active_fault_code_count

No row is inserted or deleted, so asset counts are unaffected. Values stay
inside the range the fleet already contains: oil life down to 0.5% against an
observed minimum of 1.0%, and fault counts capped at the observed maximum of
10. Oil is the only component the models can move inside these horizons without
exceeding that range, because its training event rate is 17% against 2-4% for
the others.

    python scripts/seed_survival_at_risk.py                 # dry run
    python scripts/seed_survival_at_risk.py --apply         # write
    python scripts/seed_survival_at_risk.py --restore FILE  # undo from a backup
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

_here = Path(__file__).resolve()
_root = next(p for p in _here.parents if (p / "app" / "__init__.py").exists())
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from dotenv import load_dotenv

load_dotenv(_root / ".env")

from sqlalchemy import text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.ai.services.survival_service import (  # noqa: E402
    build_asset_feature_dict,
    COMPONENTS,
    _score_component,
)

# How many assets per warehouse land in each window.
PLAN = {
    "LankaLogix - Colombo": {"urgent": 8, "soon": 8},
    "LankaLogix - Galle":   {"urgent": 5, "soon": 5},
    "LankaLogix - Badulla": {"urgent": 5, "soon": 5},
}

# Target windows for the soonest component's median predicted life, in days.
WINDOWS = {"urgent": (2.0, 6.5), "soon": (10.0, 27.0)}

# Bounds the search may use. Both sit inside the fleet's observed range.
OIL_MIN, OIL_MAX = 0.5, 45.0
FAULT_MIN, FAULT_MAX = 0, 10

COHORT_SIZE = 25          # matches the survival page's LIMIT

# Readings before the newest that get walked down towards the target, and the
# largest step allowed between two of them. The RUL trend fit reads any step of
# 15 points or more as a service event, so the ceiling sits below that.
TAPER_READINGS = 3
STEP_PCT = 12.0

BACKUP_DIR = _root / "scripts" / "backups"


def cohort(db, warehouse_name: str) -> list[tuple[str, str]]:
    """The assets the survival page scores for one warehouse, in its own order."""
    return db.execute(text("""
        SELECT a.asset_code, a.id::text
        FROM pdm_batch_predictions p
        JOIN assets a     ON a.id = p.asset_id
        JOIN warehouses w ON w.id = a.warehouse_id
        WHERE w.name = :wh
          AND p.status = 'ok'
          AND p.health_score IS NOT NULL
        ORDER BY p.health_score ASC
        LIMIT :n
    """), {"wh": warehouse_name, "n": COHORT_SIZE}).fetchall()


def soonest_median(feat: dict) -> tuple[str | None, float]:
    """Component with the shortest median life, and that median."""
    best_c, best_md = None, float("inf")
    for c in COMPONENTS:
        try:
            md = _score_component(feat, c)["median_days"]
        except Exception:
            continue
        if md == md and md < best_md:
            best_md, best_c = md, c
    return best_c, best_md


def search(feat: dict, low: float, high: float) -> tuple[float, int, float] | None:
    """Find (oil_life_pct, fault_count) putting the soonest median inside a window.

    Oil life is bisected at each fault count, lowest fault count first, so the
    mildest change that reaches the target is the one chosen.
    """
    for faults in range(FAULT_MIN, FAULT_MAX + 1):
        probe = dict(feat)
        probe["active_fault_code_count"] = faults

        probe["oil_life_pct"] = OIL_MIN
        _, md_at_min = soonest_median(probe)
        if md_at_min > high:
            continue                      # even the harshest oil value is too slow

        lo_oil, hi_oil = OIL_MIN, OIL_MAX
        for _ in range(24):
            mid = (lo_oil + hi_oil) / 2
            probe["oil_life_pct"] = mid
            _, md = soonest_median(probe)
            if low <= md <= high:
                return round(mid, 2), faults, round(md, 2)
            if md > high:
                hi_oil = mid              # too slow, degrade further
            else:
                lo_oil = mid              # too fast, ease off
        probe["oil_life_pct"] = lo_oil
        _, md = soonest_median(probe)
        if low <= md <= high:
            return round(lo_oil, 2), faults, round(md, 2)
    return None


def recent_readings(db, asset_id: str, n: int = TAPER_READINGS + 1):
    """The asset's most recent readings, newest first."""
    return db.execute(text("""
        SELECT id, oil_life_pct, active_fault_code_count, recorded_at::date
        FROM sensor_readings
        WHERE asset_id = CAST(:a AS uuid)
        ORDER BY recorded_at DESC
        LIMIT :n
    """), {"a": asset_id, "n": n}).fetchall()


def taper(rows, target_oil: float, target_faults: int) -> list[dict]:
    """Edit the newest reading, and only smooth backwards if the step demands it.

    Oil life saw-tooths naturally, since a service refills it, so the series is
    not monotone and a drop is not by itself out of character. What must not
    appear is a step the RUL trend fit reads as a service event: it treats any
    change of 15 points or more between consecutive readings as one, and fits
    the trend only to points after it.

    Candidates are chosen for already sitting near the target, so in most cases
    the newest reading moves a point or two and nothing behind it is touched.
    Earlier readings are pulled down only while the step into the target still
    exceeds the limit.
    """
    newest = rows[0]
    plan = [{
        "reading_id": int(newest[0]), "recorded": str(newest[3]),
        "old_oil": float(newest[1] or 0.0), "old_faults": int(newest[2] or 0),
        "new_oil": target_oil, "new_faults": target_faults,
    }]

    # Walk backwards from the target, capping each step. Stop as soon as a
    # reading is already close enough to leave alone.
    limit = target_oil
    for r in rows[1:]:
        current = float(r[1] or 0.0)
        limit += STEP_PCT
        if current <= limit:
            break
        plan.append({
            "reading_id": int(r[0]), "recorded": str(r[3]),
            "old_oil": current, "old_faults": int(r[2] or 0),
            "new_oil": round(limit, 2), "new_faults": int(r[2] or 0),
        })
    return plan


def max_consecutive_step(rows, edits: list[dict]) -> tuple[float, float]:
    """Largest gap between neighbouring readings, before and after the edits.

    The per-row edit size is not the quantity that matters. A row moved 50
    points is harmless if its neighbours moved with it; what the trend fit
    reacts to is the gap left between one reading and the next.

    Both figures are needed because the generated series already contains large
    jumps of its own. Only the change between the two says whether this script
    made a series worse.
    """
    def widest(series: list[float]) -> float:
        return max((abs(series[i] - series[i - 1]) for i in range(1, len(series))),
                   default=0.0)

    new_by_id = {e["reading_id"]: e["new_oil"] for e in edits}
    before = [float(r[1] or 0.0) for r in rows]
    after = [new_by_id.get(int(r[0]), float(r[1] or 0.0)) for r in rows]
    return widest(before), widest(after)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the changes")
    ap.add_argument("--restore", metavar="FILE", help="undo from a backup file")
    args = ap.parse_args()

    if args.restore:
        return restore(Path(args.restore))

    with SessionLocal() as db:
        before_assets = db.execute(text("SELECT count(*) FROM assets")).scalar()
        before_readings = db.execute(text("SELECT count(*) FROM sensor_readings")).scalar()

        planned: list[dict] = []
        used: set[str] = set()

        for wh, wants in PLAN.items():
            rows = cohort(db, wh)
            if not rows:
                print(f"  {wh}: no cohort, skipping")
                continue
            pool = [r for r in rows if r[0] not in used]
            print(f"\n{wh}  (cohort {len(rows)})")

            # Solve every candidate once, then take the ones needing the least
            # disturbance. Editing an asset already close to the target keeps
            # the recorded history closer to what the fleet generated.
            solved: dict[str, list] = {"urgent": [], "soon": []}
            for code, aid in pool:
                try:
                    feat = build_asset_feature_dict(db, aid)
                except Exception:
                    continue
                rows_recent = recent_readings(db, aid)
                if not rows_recent:
                    continue
                current_oil = float(rows_recent[0][1] or 0.0)
                for bucket in ("urgent", "soon"):
                    found = search(feat, *WINDOWS[bucket])
                    if not found:
                        continue
                    oil, faults, md = found
                    solved[bucket].append({
                        "code": code, "aid": aid, "rows": rows_recent,
                        "oil": oil, "faults": faults, "median": md,
                        "delta": abs(current_oil - oil),
                    })

            for bucket in ("urgent", "soon"):
                need = wants[bucket]
                got = 0
                for cand in sorted(solved[bucket], key=lambda c: c["delta"]):
                    if got >= need:
                        break
                    if cand["code"] in used:
                        continue
                    edits = taper(cand["rows"], cand["oil"], cand["faults"])
                    step_before, step_after = max_consecutive_step(cand["rows"], edits)
                    planned.append({
                        "warehouse": wh, "bucket": bucket,
                        "asset_code": cand["code"], "asset_id": cand["aid"],
                        "median_days": cand["median"],
                        "step_before": round(step_before, 1),
                        "step_after": round(step_after, 1),
                        "edits": edits,
                    })
                    used.add(cand["code"])
                    got += 1
                    head = edits[0]
                    print(f"   {bucket:<7}{cand['code']:<16}"
                          f"oil {head['old_oil']:>5.1f}% -> {head['new_oil']:>5.2f}%   "
                          f"faults {head['old_faults']} -> {head['new_faults']}   "
                          f"median {cand['median']:>6.2f}d   "
                          f"{len(edits)} row{'s' if len(edits) != 1 else ' '}   "
                          f"step {step_before:>5.1f} -> {step_after:>5.1f}")
                if got < need:
                    print(f"   {bucket}: wanted {need}, reachable {got}")

        urgent = [p for p in planned if p["bucket"] == "urgent"]
        soon = [p for p in planned if p["bucket"] == "soon"]
        n_rows = sum(len(p["edits"]) for p in planned)
        print(f"\n{'APPLY' if args.apply else 'DRY RUN'}: "
              f"{len(urgent)} asset(s) inside 7 days, {len(soon)} inside 30 days, "
              f"{len(planned)} assets / {n_rows} readings to update")

        worsened = [p for p in planned if p["step_after"] > p["step_before"] + 0.05]
        newly_over = [p for p in planned
                      if p["step_after"] >= 15.0 > p["step_before"]]
        already_over = [p for p in planned if p["step_before"] >= 15.0]

        print(f"series smoothness (15-point service-event threshold):")
        print(f"  widened by this script      : {len(worsened)}")
        print(f"  pushed over the threshold   : {len(newly_over)}"
              f"{'  ' + ', '.join(p['asset_code'] for p in newly_over) if newly_over else ''}")
        print(f"  already over before any edit: {len(already_over)}"
              f"{'  ' + ', '.join(p['asset_code'] for p in already_over[:6]) if already_over else ''}")

        if not args.apply:
            print("\nNothing written. Re-run with --apply to commit these values.")
            return 0

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = BACKUP_DIR / f"survival_at_risk_{stamp}.json"
        backup.write_text(json.dumps(planned, indent=1), encoding="utf-8")
        print(f"backup written: {backup.name}")

        for p in planned:
            for e in p["edits"]:
                db.execute(text("""
                    UPDATE sensor_readings
                    SET oil_life_pct = :oil, active_fault_code_count = :faults
                    WHERE id = :rid
                """), {"oil": e["new_oil"], "faults": e["new_faults"], "rid": e["reading_id"]})
        db.commit()

        after_assets = db.execute(text("SELECT count(*) FROM assets")).scalar()
        after_readings = db.execute(text("SELECT count(*) FROM sensor_readings")).scalar()
        print(f"\nassets   {before_assets} -> {after_assets}"
              f"   {'OK' if before_assets == after_assets else 'CHANGED — INVESTIGATE'}")
        print(f"readings {before_readings} -> {after_readings}"
              f"   {'OK' if before_readings == after_readings else 'CHANGED — INVESTIGATE'}")
        return 0 if before_assets == after_assets else 1


def restore(path: Path) -> int:
    planned = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    with SessionLocal() as db:
        for p in planned:
            for e in p["edits"]:
                db.execute(text("""
                    UPDATE sensor_readings
                    SET oil_life_pct = :oil, active_fault_code_count = :faults
                    WHERE id = :rid
                """), {"oil": e["old_oil"], "faults": e["old_faults"], "rid": e["reading_id"]})
                n += 1
        db.commit()
    print(f"restored {n} reading(s) across {len(planned)} asset(s) from {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
