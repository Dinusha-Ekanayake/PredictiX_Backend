"""The decision layer turns three model signals into one recommendation.

It reads health through the shared bands. When it carried its own thresholds
the "healthy" tier was unreachable and "conflict" fired on assets that were not
actually in conflict, so these tests check reachability as well as behaviour.
"""
import pytest

from app.ai.services.pdm_decision_service import (
    _classifier_tier,
    _health_tier,
    build_decision,
    classifier_only_tier,
)

CLF_THRESHOLD = 0.52          # the v7 classifier's tuned operating point
OBSERVED_MAX_SCORE = 79.0     # highest health_score the fleet produces


def decide(prob, health, days=30, saturated=False):
    return build_decision(
        failure_probability=prob,
        maintenance_required=prob >= CLF_THRESHOLD,
        days_until_maintenance=days,
        predicted_maintenance_date=None,
        health_score=health,
        horizon_saturated=saturated,
        clf_threshold=CLF_THRESHOLD,
    )


# ── tier mapping ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "score, expected",
    [(77.6, "healthy"), (60, "healthy"), (50, "healthy"),
     (49.9, "watch"), (38, "watch"), (25, "watch"),
     (24.9, "urgent"), (0, "urgent")],
)
def test_health_tier_follows_the_shared_bands(score, expected):
    assert _health_tier(score) == expected


def test_health_tier_is_reachable_in_all_three_states():
    """Guards the exact defect that made 'healthy' impossible: a cut-off
    above the highest score the fleet can produce."""
    reachable = {_health_tier(s) for s in range(0, int(OBSERVED_MAX_SCORE) + 1)}
    assert reachable == {"healthy", "watch", "urgent"}


def test_unscorable_health_is_treated_as_watch():
    """Absence of a score is not evidence of health or of failure."""
    assert _health_tier(None) == "watch"


@pytest.mark.parametrize(
    "prob, expected",
    [(0.9, "urgent"), (0.52, "urgent"), (0.51, "watch"), (0.25, "watch"), (0.0, "healthy")],
)
def test_classifier_tier_boundaries(prob, expected):
    assert _classifier_tier(prob, CLF_THRESHOLD) == expected


def test_classifier_only_tier_matches_the_full_reconciliation():
    """A probability-only estimate must never disagree with the combined one
    for the same probability."""
    for p in (0.0, 0.24, 0.25, 0.51, 0.52, 0.99):
        if _health_tier(70) == "healthy":
            assert classifier_only_tier(p, CLF_THRESHOLD) == _classifier_tier(p, CLF_THRESHOLD)


# ── combined decision ─────────────────────────────────────────────────────

def test_every_tier_is_producible():
    tiers = {
        decide(0.9, 70)["tier"],    # classifier urgent
        decide(0.3, 70)["tier"],    # classifier watch
        decide(0.1, 70)["tier"],    # both healthy
        decide(0.1, 10)["tier"],    # classifier healthy, health critical
    }
    assert tiers == {"urgent", "watch", "healthy", "conflict"}


def test_classifier_urgent_always_wins():
    """A high failure probability is actionable regardless of health score."""
    for health in (0, 30, 50, 79):
        assert decide(0.9, health)["tier"] == "urgent"


def test_conflict_only_when_classifier_is_calm_and_health_is_critical():
    assert decide(0.1, 10)["tier"] == "conflict"
    # health merely poor, not critical, is a watch rather than a conflict
    assert decide(0.1, 30)["tier"] == "watch"
    # classifier not calm means it is not a conflict
    assert decide(0.6, 10)["tier"] == "urgent"


def test_agreement_is_true_only_when_both_sides_say_the_same_thing():
    assert decide(0.1, 70)["agreement"] is True      # healthy / healthy
    assert decide(0.9, 10)["agreement"] is True      # urgent / urgent
    assert decide(0.1, 10)["agreement"] is False     # healthy / urgent


# ── how the date is presented ─────────────────────────────────────────────

def test_hard_date_only_for_urgent():
    assert decide(0.9, 20)["display_mode"] == "date"
    assert decide(0.3, 70)["display_mode"] == "soft_estimate"


def test_saturated_horizon_is_phrased_as_a_horizon_not_a_date():
    d = decide(0.1, 70, days=365, saturated=True)
    assert d["tier"] == "healthy"
    assert d["display_mode"] == "horizon"
    assert d["horizon_text"] and "months" in d["horizon_text"]


def test_every_decision_carries_an_action():
    for prob, health in ((0.9, 20), (0.3, 45), (0.1, 70), (0.1, 10)):
        assert decide(prob, health)["recommended_action"]
