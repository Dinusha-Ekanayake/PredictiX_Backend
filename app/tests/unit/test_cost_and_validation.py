"""Cost estimates and prediction-input validation.

The rules pinned here are about honesty: a missing model must produce no
number rather than a guessed one, an interval must contain its own estimate,
and a bad request must be a client error rather than a crash inside the model.
"""
import pytest
from fastapi import HTTPException

from app.ai.services.batch_prediction_service import _estimate_cost, _fmt_cost
from app.ai.services.prediction_service import validate_payload_fields


# ── cost: no model, no number ─────────────────────────────────────────────

class _Asset:
    id = "11111111-2222-3333-4444-555555555555"
    asset_code = "TEST-0001"


def test_no_cost_model_yields_no_estimate():
    """A guessed cost stored beside real ones cannot be told apart later."""
    assert _estimate_cost({}, 0.5, 30, asset=_Asset(), breakdown_cost_bundle=None) == (None, None, None)


def test_no_asset_yields_no_estimate():
    assert _estimate_cost({}, 0.5, 30, asset=None, breakdown_cost_bundle={"x": 1}) == (None, None, None)


def test_model_failure_yields_no_estimate():
    """A bundle that blows up mid-prediction must not fall back to a formula."""
    assert _estimate_cost({}, 0.5, 30, asset=_Asset(), breakdown_cost_bundle={"bad": "bundle"}) == (None, None, None)


def test_cost_is_all_or_nothing():
    """Never a point estimate without bounds, or bounds without an estimate."""
    est, lo, hi = _estimate_cost({}, 0.5, 30, asset=_Asset(), breakdown_cost_bundle=None)
    assert (est is None) == (lo is None) == (hi is None)


@pytest.mark.parametrize("value, expected", [(None, "n/a"), (0, "0"), (42500.4, "42500")])
def test_fmt_cost_handles_missing_values(value, expected):
    """Log formatting must survive a null cost instead of raising."""
    assert _fmt_cost(value) == expected


# ── prediction input validation ───────────────────────────────────────────

REQUIRED = ["snapshot_date", "tire_health_pct"]


def test_missing_key_is_a_client_error():
    with pytest.raises(HTTPException) as exc:
        validate_payload_fields({}, REQUIRED)
    assert exc.value.status_code == 422


def test_present_but_none_is_also_missing():
    """Pydantic emits every optional field as None, so a presence-only check
    passes an empty body straight through to the model."""
    with pytest.raises(HTTPException) as exc:
        validate_payload_fields({"snapshot_date": None, "tire_health_pct": None}, REQUIRED)
    assert exc.value.status_code == 422
    assert set(exc.value.detail["missing_fields"]) == set(REQUIRED)


def test_complete_payload_passes():
    validate_payload_fields({"snapshot_date": "2026-08-12", "tire_health_pct": 72}, REQUIRED)


def test_zero_is_a_real_value_not_a_missing_one():
    """0 is falsy but perfectly valid for a health percentage."""
    validate_payload_fields({"snapshot_date": "2026-08-12", "tire_health_pct": 0}, REQUIRED)
