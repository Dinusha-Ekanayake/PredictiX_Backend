"""Per-asset component Remaining Useful Life (RUL) estimation.

Deliberately independent of app/ai/services/survival_service.py (the Weibull
AFT models used for warehouse-level report generation). This module never
imports it and never touches app/ai/models/survival_analysis/.

Method: for each component (tire, brake, battery, oil, hydraulic), fit a
simple linear trend of that asset's own sensor_readings health-percentage
history over time, then extrapolate forward to the day the trend crosses
that component's failure threshold. This is a per-asset statistical
estimate computed fresh from that asset's own data — there is no per-
component failure-event label in the training data (the v11 dataset only
labels a whole-asset "next maintenance" outcome), so a real per-component
ML model cannot be trained today. See docs/rul-methodology.md-equivalent
notes below for why this is a deliberate, documented limitation rather than
an oversight.

Model grounding (hybrid approach)
----------------------------------
A 4-point OLS trend is statistically thin — projections from it can swing
from "1 year left" to "8 years left" for the same asset depending on
reading-to-reading noise alone. Rather than presenting that raw extrapolation
with false confidence, every component RUL here is cross-checked against the
v7 regressor's own whole-asset prediction (from the latest PdmBatchPrediction
row, which SHAP already explains in terms of these same health-pct fields):

  - `horizon_capped`: any component RUL beyond a sane physical ceiling (2
    years) is clamped and flagged, mirroring the regressor's own
    horizon_saturated treatment instead of showing e.g. a 2034 failure date.
  - `model_corroborated`: True if this component's health field is among the
    regressor's top SHAP factors for THIS asset — i.e. the trained model
    independently considers this component's reading important to the
    overall maintenance timeline, not just the local 4-point trend.
  - `model_days_ceiling`: the regressor's own predicted_days_until_maintenance
    for the whole asset. A component cannot credibly need service *later*
    than the model's overall next-maintenance estimate by an implausible
    margin — if the OLS trend disagrees sharply with the model here, the
    component is flagged for review rather than the OLS number being trusted
    silently.

With fewer than two readings there's no trend to fit, so a single-point
estimate is returned instead (current health only, no history), and is
clearly flagged as low confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy import asc
from sqlalchemy.orm import Session

from app.models import Asset, PdmBatchPrediction, SensorReading

# Component-specific failure thresholds (% health at which the component is
# considered failed/due for replacement). Safety-critical components that
# degrade to a hard failure (tire, brake, hydraulic) are given a higher
# (more conservative) threshold than components with a softer failure mode
# (oil life, battery) — these are documented starting assumptions, not
# fitted values; see the module docstring.
FAILURE_THRESHOLD_PCT: dict[str, float] = {
    "tire": 30.0,
    "brake": 35.0,
    "hydraulic": 30.0,
    "oil": 15.0,
    "battery": 20.0,
}
MIN_POINTS_FOR_TREND = 2

# A component-level RUL beyond this is not a meaningful "prediction" given
# only 4 monthly readings — it's noise extrapolated a decade out. Clamp and
# flag instead of showing e.g. "3096 days left" / a 2034 failure date.
MAX_HORIZON_DAYS = 730

# A jump this large between two consecutive monthly readings (e.g. oil life
# jumping from 53% to 85%) is almost certainly a maintenance/service event,
# not gradual physical change — a straight-line fit across it produces a
# large slope that is real (not noise) but describes a one-time step, not
# an ongoing trend. Detected and relabelled rather than blended into the fit.
SERVICE_EVENT_JUMP_PCT = 15.0

COMPONENTS: dict[str, str] = {
    "tire": "tire_health_pct",
    "brake": "brake_health_pct",
    "battery": "battery_health_pct",
    "oil": "oil_life_pct",
    "hydraulic": "hydraulic_health_pct",
}


@dataclass
class ComponentRul:
    component: str
    current_health_pct: Optional[float]
    degradation_pct_per_day: Optional[float]
    rul_days: Optional[int]
    rul_days_low: Optional[int]
    rul_days_high: Optional[int]
    estimated_failure_date: Optional[date]
    confidence: str  # "trend" | "insufficient_trend" | "single_point" | "no_data" | "recently_serviced"
    readings_used: int
    horizon_capped: bool = False
    model_corroborated: bool = False
    model_days_ceiling: Optional[int] = None
    disagrees_with_model: bool = False
    # True when this estimate was refit on the window *since* a detected
    # service-event jump rather than the asset's full reading history —
    # i.e. "recently serviced, and here's the trend since then" instead of
    # "recently serviced, no post-service trend available yet".
    post_service: bool = False


def _linear_fit_with_se(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """OLS slope/intercept plus the standard error of the slope.

    The SE lets us turn a single point estimate into an honest uncertainty
    band instead of presenting a bare day-count as if it were precise —
    with only 4 observations that band is wide, which is the point: it
    should look uncertain, because it is.
    """
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return 0.0, mean_y, 0.0

    slope = num / den
    intercept = mean_y - slope * mean_x

    if n <= 2:
        return slope, intercept, 0.0

    residual_ss = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    dof = n - 2
    residual_var = residual_ss / dof if dof > 0 else 0.0
    se_slope = (residual_var / den) ** 0.5 if den > 0 else 0.0
    return slope, intercept, se_slope


def _rul_from_slope(last_health: float, threshold: float, slope: float) -> Optional[int]:
    if slope >= 0:
        return None
    days = (threshold - last_health) / slope
    return max(0, int(days))


def _detect_jump_index(points: list[tuple[datetime, float]]) -> Optional[int]:
    """Index of the reading right after the largest jump between consecutive
    points, if that jump is large enough to look like a service event.
    Returns None if no jump clears the threshold."""
    if len(points) < 2:
        return None
    deltas = [abs(points[i][1] - points[i - 1][1]) for i in range(1, len(points))]
    best_i = max(range(len(deltas)), key=lambda i: deltas[i])
    if deltas[best_i] >= SERVICE_EVENT_JUMP_PCT:
        return best_i + 1  # points[] index of the reading after the jump
    return None


def _fit_trend_from_points(
    component: str,
    threshold: float,
    points: list[tuple[datetime, float]],
    post_service: bool,
) -> ComponentRul:
    """OLS-fit a trend on `points` and classify it into a ComponentRul.

    Shared by the whole-history fit and the post-service-jump refit — same
    significance test and RUL/uncertainty-band logic either way, just a
    different (and possibly shorter) window of readings.
    """
    t0 = points[0][0]
    xs = [(t - t0).total_seconds() / 86400.0 for t, _ in points]
    ys = [v for _, v in points]
    slope, intercept, se_slope = _linear_fit_with_se(xs, ys)

    last_health = ys[-1]

    # A slope within its own standard error of zero is not evidence of a
    # real trend in either direction — with only a handful of points,
    # "slightly positive" and "slightly negative" are both indistinguishable
    # from noise. Labelling that "Improving" (or extrapolating a failure
    # date from it) claims a confidence the data doesn't support; the honest
    # answer is that there isn't enough signal to say which way this
    # component is trending yet.
    is_significant = se_slope == 0 or abs(slope) > se_slope

    if not is_significant:
        return ComponentRul(
            component=component,
            current_health_pct=round(last_health, 1),
            degradation_pct_per_day=round(slope, 4),
            rul_days=None,
            rul_days_low=None,
            rul_days_high=None,
            estimated_failure_date=None,
            confidence="insufficient_trend",
            readings_used=len(points),
            post_service=post_service,
        )

    if slope >= 0:
        # Genuinely improving (e.g. component condition recovering) — the
        # slope clears the noise floor and points upward, a real signal.
        return ComponentRul(
            component=component,
            current_health_pct=round(last_health, 1),
            degradation_pct_per_day=round(slope, 4),
            rul_days=None,
            rul_days_low=None,
            rul_days_high=None,
            estimated_failure_date=None,
            confidence="trend",
            readings_used=len(points),
            post_service=post_service,
        )

    rul_days = _rul_from_slope(last_health, threshold, slope)
    assert rul_days is not None  # slope < 0 here, so this always resolves

    # Uncertainty band from the slope's standard error (±1 SE on the slope,
    # propagated through the same extrapolation). With few points this is
    # necessarily wide — that width is the honest signal, not a defect.
    rul_low, rul_high = rul_days, rul_days
    if se_slope > 0:
        slope_low = slope - se_slope   # steeper decline → shorter RUL
        slope_high = slope + se_slope  # shallower decline → longer RUL
        if slope_low < 0:
            rul_high = _rul_from_slope(last_health, threshold, slope_low) or rul_days
        if slope_high < 0:
            rul_low = _rul_from_slope(last_health, threshold, slope_high) or rul_days
        else:
            rul_low = rul_days  # shallow-side SE flips to improving — can't bound further out
        rul_low, rul_high = min(rul_low, rul_high), max(rul_low, rul_high)

    capped = rul_days > MAX_HORIZON_DAYS
    rul_days_final = min(rul_days, MAX_HORIZON_DAYS)
    rul_low = min(rul_low, MAX_HORIZON_DAYS)
    rul_high = min(rul_high, MAX_HORIZON_DAYS)

    return ComponentRul(
        component=component,
        current_health_pct=round(last_health, 1),
        degradation_pct_per_day=round(slope, 4),
        rul_days=rul_days_final,
        rul_days_low=rul_low,
        rul_days_high=rul_high,
        estimated_failure_date=date.today().fromordinal(date.today().toordinal() + rul_days_final),
        confidence="trend",
        readings_used=len(points),
        horizon_capped=capped,
        post_service=post_service,
    )


def _estimate_component(
    component: str,
    readings: list[tuple[datetime, Optional[float]]],
) -> ComponentRul:
    threshold = FAILURE_THRESHOLD_PCT[component]
    points = [(t, float(v)) for t, v in readings if v is not None]

    if not points:
        return ComponentRul(
            component=component,
            current_health_pct=None,
            degradation_pct_per_day=None,
            rul_days=None,
            rul_days_low=None,
            rul_days_high=None,
            estimated_failure_date=None,
            confidence="no_data",
            readings_used=0,
        )

    current_health = points[-1][1]

    if len(points) < MIN_POINTS_FOR_TREND:
        # Not enough history for a trend — fall back to a generic, clearly
        # low-confidence degradation assumption (0.05%/day, ~20 years to
        # threshold from 100%) so the UI still has *something* to show,
        # honestly labelled and still subject to the same horizon cap.
        assumed_rate = 0.05
        rul_days = None
        if current_health > threshold:
            rul_days = int((current_health - threshold) / assumed_rate)
        capped = rul_days is not None and rul_days > MAX_HORIZON_DAYS
        if capped:
            rul_days = MAX_HORIZON_DAYS
        return ComponentRul(
            component=component,
            current_health_pct=round(current_health, 1),
            degradation_pct_per_day=None,
            rul_days=rul_days,
            rul_days_low=None,
            rul_days_high=None,
            estimated_failure_date=(
                date.today().fromordinal(date.today().toordinal() + rul_days) if rul_days else None
            ),
            confidence="single_point",
            readings_used=len(points),
            horizon_capped=capped,
        )

    # A large jump between two consecutive readings (e.g. an oil change
    # taking oil_life_pct from 53% to 85%) is almost certainly a maintenance
    # event, not gradual physical change. A straight-line fit across it
    # would produce a slope that IS statistically real (not noise) but
    # describes that one-time step rather than an ongoing trend. Rather
    # than just flagging and giving up, refit the trend using only the
    # readings from that event onward — that's the component's actual
    # current trajectory, not one blended with its stale pre-service history.
    jump_idx = _detect_jump_index(points)
    if jump_idx is not None:
        post_service_points = points[jump_idx:]
        if len(post_service_points) >= MIN_POINTS_FOR_TREND:
            return _fit_trend_from_points(component, threshold, post_service_points, post_service=True)

        # Only one reading since the service event — can't fit a line yet,
        # so there's genuinely no trend to report, just the fact of the
        # recent service and its single follow-up reading.
        return ComponentRul(
            component=component,
            current_health_pct=round(current_health, 1),
            degradation_pct_per_day=None,
            rul_days=None,
            rul_days_low=None,
            rul_days_high=None,
            estimated_failure_date=None,
            confidence="recently_serviced",
            readings_used=len(points),
        )

    return _fit_trend_from_points(component, threshold, points, post_service=False)


def _apply_model_grounding(
    results: list[ComponentRul],
    batch_prediction: Optional[PdmBatchPrediction],
) -> None:
    """Cross-check each component's OLS-derived RUL against the v7
    regressor's own whole-asset prediction. Mutates `results` in place.

    - model_corroborated: this component's health field is among the
      regressor's top SHAP factors for this asset, i.e. the trained model
      (not just the local 4-point trend) independently flags it as
      relevant to the maintenance timeline.
    - disagrees_with_model: this component's trend claims to be fine
      substantially *longer* than the whole-asset model's own maintenance
      timeline — the model is trained on 96,827 rows and already consumes
      this component's reading as one of its 58 features, so when the
      4-point trend is far more optimistic than the model, that's the trend
      likely being wrong (noise), not the model. Surfaced rather than
      silently trusting the weaker signal, same philosophy as the
      classifier/health-score `agreement` check in the decision layer.

      Uses a proportional gap (component RUL more than double the model's
      ceiling, plus a fixed absolute floor) rather than a fixed "only when
      the model says <=60 days" cutoff — a component claiming 730+ days
      while the model's own ceiling is 98 days is just as much a real
      disagreement as one claiming 200 days while the model says 20.
    """
    if batch_prediction is None or batch_prediction.predicted_days_until_maintenance is None:
        return

    model_days = int(batch_prediction.predicted_days_until_maintenance)
    shap_features = {
        (f.get("feature") or "") for f in (batch_prediction.top_explanations or [])
    }

    for r in results:
        r.model_days_ceiling = model_days
        component_field = COMPONENTS.get(r.component)
        r.model_corroborated = component_field in shap_features

        if r.rul_days is None:
            continue

        # Flag when the component's own trend claims a runway meaningfully
        # longer than the model's whole-asset ceiling — both an absolute
        # margin (so a 35d vs 20d gap isn't flagged as "disagreement") and a
        # relative one (so the gap scales with the model's own horizon).
        gap = r.rul_days - model_days
        r.disagrees_with_model = gap > 60 and r.rul_days > model_days * 2


def compute_asset_component_rul(
    db: Session,
    asset_id: str,
    batch_prediction: Optional[PdmBatchPrediction] = None,
) -> list[ComponentRul]:
    """Return a per-component RUL estimate for one asset, computed from that
    asset's own sensor_readings history and grounded against the latest v7
    whole-asset prediction. Raises ValueError if the asset doesn't exist.

    ``batch_prediction`` lets a caller that already fetched the asset's
    PdmBatchPrediction row (e.g. the asset detail page's own prediction
    lookup) pass it straight in instead of this function re-querying the
    same row — pass ``None`` (the default) to have it fetched here.
    """
    asset = db.query(Asset.id).filter(Asset.id == asset_id).first()
    if asset is None:
        raise ValueError(f"Asset {asset_id} not found")

    rows = (
        db.query(
            SensorReading.recorded_at,
            SensorReading.tire_health_pct,
            SensorReading.brake_health_pct,
            SensorReading.battery_health_pct,
            SensorReading.oil_life_pct,
            SensorReading.hydraulic_health_pct,
        )
        .filter(SensorReading.asset_id == asset_id)
        .order_by(asc(SensorReading.recorded_at))
        .all()
    )

    results: list[ComponentRul] = []
    for component, column_alias in COMPONENTS.items():
        idx = {
            "tire_health_pct": 1,
            "brake_health_pct": 2,
            "battery_health_pct": 3,
            "oil_life_pct": 4,
            "hydraulic_health_pct": 5,
        }[column_alias]
        series = [(r[0], r[idx]) for r in rows]
        results.append(_estimate_component(component, series))

    if batch_prediction is None:
        batch_prediction = (
            db.query(PdmBatchPrediction)
            .filter(PdmBatchPrediction.asset_id == asset_id)
            .first()
        )
    _apply_model_grounding(results, batch_prediction)

    return results
