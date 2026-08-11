"""PdM decision layer — reconciles classifier + regressor + health score into
one tiered recommendation instead of three independently-speaking numbers.

Problem this solves: the classifier, regressor, and health score each answer
a different question (should we act? / when? / how healthy is it overall?),
but were previously surfaced to the UI independently — producing confusing
combinations like "maintenance not required" next to a specific hard date.

This module makes the classifier the gatekeeper: it decides whether a date
is even actionable. The regressor's date is only shown as a hard commitment
when the classifier agrees action is needed soon; otherwise it's demoted to
a soft "no service expected for ~N months" framing. Purely additive — it
does not change what the classifier/regressor/health-score compute, only how
their outputs are interpreted together.
"""
from __future__ import annotations

from typing import Any

# Tier thresholds derived from the v7 classifier's own tuned operating point
# (threshold_max_f1, currently 0.52 — see classifier_v7_decision_log.json),
# not a guessed constant. A lower "watch" band sits under it so borderline
# cases aren't silently rounded into "healthy".
_WATCH_PROBABILITY_FLOOR = 0.25
_WATCH_HEALTH_CEILING = 60.0
_HEALTHY_HEALTH_FLOOR = 80.0
_CONFLICT_HEALTH_CEILING = 40.0


def _classifier_tier(failure_probability: float, urgent_threshold: float) -> str:
    if failure_probability >= urgent_threshold:
        return "urgent"
    if failure_probability >= _WATCH_PROBABILITY_FLOOR:
        return "watch"
    return "healthy"


def classifier_only_tier(failure_probability: float, clf_threshold: float) -> str:
    """The classifier-alone tier ("urgent" | "watch" | "healthy"), for
    callers that don't have a health_score available to run the full
    build_decision reconciliation below — e.g. the standalone
    /predictions/classification debug endpoint. Uses the exact same
    threshold boundaries build_decision does, so a probability-only
    estimate can never disagree with the fully-reconciled one for the
    same probability."""
    return _classifier_tier(failure_probability, clf_threshold)


def _health_tier(health_score: float) -> str:
    if health_score >= _HEALTHY_HEALTH_FLOOR:
        return "healthy"
    if health_score >= _WATCH_HEALTH_CEILING:
        return "watch"
    if health_score < _CONFLICT_HEALTH_CEILING:
        return "urgent"
    return "watch"


def build_decision(
    *,
    failure_probability: float,
    maintenance_required: bool,
    days_until_maintenance: int,
    predicted_maintenance_date,
    health_score: float,
    horizon_saturated: bool,
    clf_threshold: float,
) -> dict[str, Any]:
    """Combine the three PdM signals into one tiered recommendation.

    Returns a dict with:
      - tier: "urgent" | "watch" | "healthy" | "conflict"
      - agreement: bool — do the classifier-derived and health-derived tiers match?
      - display_mode: "date" | "soft_estimate" | "horizon" — how the UI should
        render the regressor's predicted_maintenance_date.
      - horizon_text: human copy to show when display_mode != "date"
      - recommended_action: short actionable string
    """
    clf_tier = _classifier_tier(failure_probability, clf_threshold)
    health_tier = _health_tier(health_score)

    if clf_tier == "urgent":
        tier = "urgent"
    elif clf_tier == "healthy" and health_tier == "urgent":
        # Classifier says fine, health score says critical — the two most
        # information-dense signals disagree. Surface it rather than average
        # it away; this is exactly the case a human should look at.
        tier = "conflict"
    elif clf_tier == "watch" or health_tier == "watch":
        tier = "watch"
    else:
        tier = "healthy"

    agreement = clf_tier == health_tier

    if tier == "urgent":
        display_mode = "date"
        horizon_text = None
        recommended_action = "Schedule maintenance immediately"
    elif tier == "watch":
        display_mode = "soft_estimate"
        horizon_text = f"Inspect soon — estimated within ~{days_until_maintenance} days"
        recommended_action = "Inspect vehicle soon"
    elif tier == "conflict":
        display_mode = "date" if days_until_maintenance <= 30 else "soft_estimate"
        horizon_text = "Classifier and health score disagree — flagged for manual review"
        recommended_action = "Review manually — signals disagree"
    else:  # healthy
        if horizon_saturated:
            months = max(1, round(days_until_maintenance / 30))
            display_mode = "horizon"
            horizon_text = f"No maintenance expected in the next ~{months} months"
        else:
            display_mode = "soft_estimate"
            horizon_text = f"Healthy — next service estimated in ~{days_until_maintenance} days"
        recommended_action = "Continue monitoring"

    return {
        "tier": tier,
        "classifier_tier": clf_tier,
        "health_tier": health_tier,
        "agreement": agreement,
        "display_mode": display_mode,
        "horizon_text": horizon_text,
        "recommended_action": recommended_action,
        "horizon_saturated": bool(horizon_saturated),
    }
