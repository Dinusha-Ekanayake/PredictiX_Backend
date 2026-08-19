"""Reconstruct monthly prediction history from the sensor readings already stored.

The dashboard's health trend reads pdm_prediction_history. That table is written
by the nightly batch and only reaches back to the day the batch started, so the
chart has one month of data while the fleet has five years of telemetry behind
it.

Every month already holds a real sensor reading per asset. This scores those
readings with the deployed v7 models and writes the result as history, so the
trend is genuine model output over genuine measurements.

What it is not: a record of what the system predicted at the time. These rows
are computed now, against readings recorded then. They carry a model_version
suffixed with `+backfill` so they stay identifiable and removable, and so the
distinction survives in the data rather than only in this docstring.

    python scripts/backfill_prediction_history.py                 # dry run
    python scripts/backfill_prediction_history.py --apply
    python scripts/backfill_prediction_history.py --months 12
    python scripts/backfill_prediction_history.py --purge          # remove them
"""
from __future__ import annotations

import argparse
import sys
import warnings
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")

_here = Path(__file__).resolve()
_root = next(p for p in _here.parents if (p / "app" / "__init__.py").exists())
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from dotenv import load_dotenv

load_dotenv(_root / ".env")

from sqlalchemy import text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import Asset  # noqa: E402
from app.services.health_bands import band_for  # noqa: E402

BACKFILL_SUFFIX = "+backfill"
CHUNK = 200


def month_starts(n: int, latest: date) -> list[date]:
    """The first day of each of the n months ending with `latest`'s month."""
    out: list[date] = []
    y, m = latest.year, latest.month
    for _ in range(n):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def existing_months(db) -> set[str]:
    return {
        r[0] for r in db.execute(text(
            "SELECT DISTINCT to_char(predicted_at, 'YYYY-MM') FROM pdm_prediction_history"
        ))
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the rows")
    ap.add_argument("--months", type=int, default=6, help="how many months back")
    ap.add_argument("--purge", action="store_true",
                    help="delete previously backfilled rows and exit")
    args = ap.parse_args()

    # The models are loaded by the app's startup, not at import, so importing
    # the names would bind None. Load them explicitly and read through the
    # module, which scores with exactly what the live pipeline uses.
    import app.main as main  # noqa: E402

    main._load_pdm_models()
    clf_model = main.clf_model
    clf_features = main.clf_features
    clf_threshold = main.clf_threshold
    clf_categorical_cols = main.clf_categorical_cols
    reg_model = main.reg_model
    reg_features = main.reg_features
    reg_categorical_cols = main.reg_categorical_cols

    if clf_model is None or reg_model is None:
        print("PdM models failed to load; nothing scored")
        return 1
    from app.ai.services.batch_prediction_service import (  # noqa: E402
        _build_feature_dict, _run_classifier_batch, _run_regressor_batch,
        _compute_health_score, _model_version_tag,
    )
    from app.ai.services.pdm_decision_service import build_decision  # noqa: E402

    version = _model_version_tag() + BACKFILL_SUFFIX

    with SessionLocal() as db:
        if args.purge:
            n = db.execute(text(
                "DELETE FROM pdm_prediction_history WHERE model_version LIKE :v RETURNING id"
            ), {"v": f"%{BACKFILL_SUFFIX}"}).rowcount
            db.commit()
            print(f"removed {n} backfilled row(s)")
            return 0

        latest_reading = db.execute(text("SELECT max(recorded_at)::date FROM sensor_readings")).scalar()
        if not latest_reading:
            print("no sensor readings, nothing to do")
            return 1

        have = existing_months(db)
        targets = [m for m in month_starts(args.months, latest_reading)
                   if m.strftime("%Y-%m") not in have]
        skipped = args.months - len(targets)

        print(f"latest reading      : {latest_reading}")
        print(f"months already held : {sorted(have)}")
        print(f"months to backfill  : {[m.strftime('%Y-%m') for m in targets]}"
              f"  ({skipped} skipped, already present)\n")
        if not targets:
            print("nothing to do")
            return 0

        assets = db.query(Asset).all()
        print(f"assets: {len(assets)}\n")

        total_rows = 0
        for month in targets:
            nxt = date(month.year + (month.month == 12), (month.month % 12) + 1, 1)
            readings = db.execute(text("""
                SELECT DISTINCT ON (asset_id) asset_id, id, recorded_at
                FROM sensor_readings
                WHERE recorded_at >= :a AND recorded_at < :b
                ORDER BY asset_id, recorded_at DESC
            """), {"a": month, "b": nxt}).fetchall()
            by_asset = {str(r[0]): r[1] for r in readings}
            if not by_asset:
                print(f"  {month:%Y-%m}: no readings in this month, skipped")
                continue

            # Load the reading objects once, keyed by asset.
            from app.models import SensorReading
            ids = list(by_asset.values())
            objs = {r.id: r for r in db.query(SensorReading)
                    .filter(SensorReading.id.in_(ids)).all()}

            snapshot = min(date(month.year, month.month, 28), latest_reading)
            pairs = [(a, objs[by_asset[str(a.id)]]) for a in assets
                     if str(a.id) in by_asset and by_asset[str(a.id)] in objs]
            feats = [_build_feature_dict(a, r, snapshot_date=snapshot) for a, r in pairs]

            written = 0
            for start in range(0, len(pairs), CHUNK):
                chunk_pairs = pairs[start:start + CHUNK]
                chunk_feats = feats[start:start + CHUNK]

                clf_out = _run_classifier_batch(
                    chunk_feats, clf_model, clf_features, clf_threshold, clf_categorical_cols)
                reg_out = _run_regressor_batch(
                    chunk_feats, reg_model, reg_features, reg_categorical_cols, snapshot)

                rows: list[dict[str, Any]] = []
                for (asset, _), fd, (prob, required), (days, due_date, _shap, saturated) in zip(
                        chunk_pairs, chunk_feats, clf_out, reg_out):
                    if prob is None:
                        continue          # a failed score is not history worth keeping
                    health, _band = _compute_health_score(fd, prob, days)
                    decision = build_decision(
                        failure_probability=prob,
                        maintenance_required=required,
                        days_until_maintenance=days,
                        predicted_maintenance_date=due_date,
                        health_score=health,
                        horizon_saturated=saturated,
                        clf_threshold=clf_threshold,
                    )
                    rows.append({
                        "asset_id": str(asset.id),
                        "failure_probability": round(float(prob), 6),
                        "predicted_days_until_maintenance": int(days),
                        "predicted_maintenance_date": due_date,
                        "health_score": float(health),
                        "tier": decision["tier"],
                        "model_version": version,
                        "predicted_at": datetime(
                            snapshot.year, snapshot.month, snapshot.day,
                            2, 0, tzinfo=timezone.utc),
                    })

                if args.apply and rows:
                    db.execute(text("""
                        INSERT INTO pdm_prediction_history
                          (id, asset_id, failure_probability,
                           predicted_days_until_maintenance, predicted_maintenance_date,
                           health_score, tier, model_version, predicted_at)
                        VALUES
                          (gen_random_uuid(), CAST(:asset_id AS uuid), :failure_probability,
                           :predicted_days_until_maintenance, :predicted_maintenance_date,
                           :health_score, :tier, :model_version, :predicted_at)
                    """), rows)
                written += len(rows)

            if args.apply:
                db.commit()
            avg = (sum(r["health_score"] for r in rows) / len(rows)) if rows else 0
            print(f"  {month:%Y-%m}: {written:>4} row(s)"
                  f"{'  written' if args.apply else '  (dry run)'}"
                  f"   last-chunk mean health {avg:.1f}")
            total_rows += written

        print(f"\n{'WROTE' if args.apply else 'WOULD WRITE'} {total_rows} row(s) "
              f"tagged model_version='{version}'")
        if not args.apply:
            print("Re-run with --apply to write. Undo at any time with --purge.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
