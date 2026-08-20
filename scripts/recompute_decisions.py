"""Recompute the decision-layer fields on existing pdm_batch_predictions rows.

The decision layer turns the stored classifier probability, regressor days and
health score into a tier and the display copy that goes with it. Those inputs
are not touched here, so this only rewrites what build_decision derives from
them: tier, agreement, display_mode, horizon_text and recommended_action.

Run it after changing the decision logic, so stored rows stop disagreeing with
what the code would produce today. The nightly batch would eventually correct
them anyway; this avoids serving stale tiers until then.

Usage:
    python scripts/recompute_decisions.py            # dry run, shows the diff
    python scripts/recompute_decisions.py --apply    # write the changes
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.ai.services.pdm_decision_service import build_decision  # noqa: E402
from app.db import SessionLocal  # noqa: E402

CLASSIFIER_LOG = (
    Path(__file__).resolve().parents[1]
    / "app" / "ai" / "models" / "pdm_classifier_model" / "classifier_v7_decision_log.json"
)

SELECT_SQL = """
    SELECT asset_id, failure_probability, maintenance_required,
           predicted_days_until_maintenance, predicted_maintenance_date,
           health_score, horizon_saturated,
           tier, agreement, display_mode, horizon_text, recommended_action
    FROM pdm_batch_predictions
    WHERE status = 'ok'
      AND health_score IS NOT NULL
      AND failure_probability IS NOT NULL
"""

UPDATE_SQL = """
    UPDATE pdm_batch_predictions
    SET tier = :tier,
        agreement = :agreement,
        display_mode = :display_mode,
        horizon_text = :horizon_text,
        recommended_action = :recommended_action
    WHERE asset_id = :asset_id
"""


def classifier_threshold() -> float:
    """The classifier's tuned operating point, same source main.py reads."""
    if not CLASSIFIER_LOG.exists():
        raise SystemExit(f"Classifier decision log not found: {CLASSIFIER_LOG}")
    return float(json.loads(CLASSIFIER_LOG.read_text()).get("threshold_max_f1", 0.5))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the changes")
    args = ap.parse_args()

    threshold = classifier_threshold()
    print(f"classifier threshold: {threshold}")

    db = SessionLocal()
    try:
        rows = db.execute(text(SELECT_SQL)).fetchall()
        before, after, moves = Counter(), Counter(), Counter()
        updates = []

        for r in rows:
            decision = build_decision(
                failure_probability=float(r.failure_probability),
                maintenance_required=bool(r.maintenance_required),
                days_until_maintenance=int(r.predicted_days_until_maintenance or 0),
                predicted_maintenance_date=r.predicted_maintenance_date,
                health_score=float(r.health_score),
                horizon_saturated=bool(r.horizon_saturated),
                clf_threshold=threshold,
            )
            before[r.tier] += 1
            after[decision["tier"]] += 1

            unchanged = (
                r.tier == decision["tier"]
                and r.agreement == decision["agreement"]
                and r.display_mode == decision["display_mode"]
                and r.horizon_text == decision["horizon_text"]
                and r.recommended_action == decision["recommended_action"]
            )
            if unchanged:
                continue

            moves[f"{r.tier} -> {decision['tier']}"] += 1
            updates.append({
                "asset_id": str(r.asset_id),
                "tier": decision["tier"],
                "agreement": decision["agreement"],
                "display_mode": decision["display_mode"],
                "horizon_text": decision["horizon_text"],
                "recommended_action": decision["recommended_action"],
            })

        print(f"\nrows examined: {len(rows)}   rows needing update: {len(updates)}")
        print(f"\n{'tier':<12}{'before':>8}{'after':>8}")
        for tier in ("healthy", "watch", "urgent", "conflict"):
            print(f"{tier:<12}{before.get(tier, 0):>8}{after.get(tier, 0):>8}")
        if moves:
            print("\ntier movements:")
            for move, n in moves.most_common():
                print(f"   {move:<26} {n}")

        if not args.apply:
            print("\ndry run. pass --apply to write these changes.")
            return

        for chunk_start in range(0, len(updates), 200):
            db.execute(text(UPDATE_SQL), updates[chunk_start:chunk_start + 200])
        db.commit()
        print(f"\napplied. {len(updates)} rows updated.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
