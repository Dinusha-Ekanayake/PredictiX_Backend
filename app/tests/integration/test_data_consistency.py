"""The stored data must agree with itself and with the code that derives it.

These check the whole fleet rather than a sample, because the failures they
guard against were systematic: a band scale that disagreed with another screen,
a cost interval that excluded its own estimate, a tier nothing could reach.
"""
import pytest
from sqlalchemy import text

from app.services.health_bands import HEALTH_BAND_NAMES, band_for

pytestmark = pytest.mark.integration

OK_ROWS = "FROM pdm_batch_predictions WHERE status = 'ok'"


def test_every_stored_band_is_a_real_band(db):
    bad = db.execute(text(f"""
        SELECT COUNT(*) {OK_ROWS}
          AND health_status IS NOT NULL
          AND health_status NOT IN :names
    """), {"names": tuple(HEALTH_BAND_NAMES)}).scalar()
    assert bad == 0


def test_stored_band_matches_the_shared_definition(db):
    """health_status must be exactly band_for(health_score)."""
    rows = db.execute(text(
        f"SELECT health_score, health_status {OK_ROWS} AND health_score IS NOT NULL"
    )).fetchall()
    assert rows, "no scored predictions to check"
    mismatched = [(float(s), st) for s, st in rows if band_for(float(s)) != st]
    assert not mismatched, f"{len(mismatched)} of {len(rows)} rows disagree, e.g. {mismatched[:3]}"


def test_prediction_band_matches_the_asset_row(db):
    """The assets list and the prediction must not label the same asset
    differently."""
    disagreeing = db.execute(text("""
        SELECT COUNT(*)
        FROM pdm_batch_predictions p
        JOIN assets a ON a.id = p.asset_id
        WHERE p.status = 'ok' AND p.health_score IS NOT NULL
          AND p.health_status IS DISTINCT FROM a.health_band::text
    """)).scalar()
    assert disagreeing == 0


def test_no_band_is_unreachable_on_real_data(db):
    """A band no asset can ever fall into means the scale is miscalibrated."""
    present = {
        row[0] for row in db.execute(text(
            f"SELECT DISTINCT health_status {OK_ROWS} AND health_status IS NOT NULL"
        )).fetchall()
    }
    assert present == set(HEALTH_BAND_NAMES), f"never produced: {set(HEALTH_BAND_NAMES) - present}"


def test_no_tier_is_unreachable_on_real_data(db):
    present = {
        row[0] for row in db.execute(text(
            f"SELECT DISTINCT tier {OK_ROWS} AND tier IS NOT NULL"
        )).fetchall()
    }
    assert present == {"healthy", "watch", "urgent", "conflict"}, f"got {present}"


def test_cost_interval_contains_its_own_estimate(db):
    incoherent = db.execute(text("""
        SELECT COUNT(*) FROM pdm_batch_predictions
        WHERE estimated_cost_lkr IS NOT NULL
          AND NOT (min_cost_lkr <= estimated_cost_lkr
                   AND estimated_cost_lkr <= max_cost_lkr)
    """)).scalar()
    assert incoherent == 0, f"{incoherent} rows have bounds that exclude the estimate"


def test_cost_fields_are_all_or_nothing(db):
    """A point estimate without bounds (or vice versa) means something
    fabricated one of them."""
    partial = db.execute(text("""
        SELECT COUNT(*) FROM pdm_batch_predictions
        WHERE (estimated_cost_lkr IS NULL) <> (min_cost_lkr IS NULL)
           OR (estimated_cost_lkr IS NULL) <> (max_cost_lkr IS NULL)
    """)).scalar()
    assert partial == 0


def test_health_scores_stay_in_range(db):
    row = db.execute(text(
        f"SELECT MIN(health_score), MAX(health_score) {OK_ROWS} AND health_score IS NOT NULL"
    )).fetchone()
    assert 0 <= float(row[0]) and float(row[1]) <= 100


def test_failure_probability_is_a_probability(db):
    bad = db.execute(text(
        f"SELECT COUNT(*) {OK_ROWS} AND failure_probability IS NOT NULL"
        "   AND (failure_probability < 0 OR failure_probability > 1)"
    )).scalar()
    assert bad == 0
