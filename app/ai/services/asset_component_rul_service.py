"""Per-asset component Remaining Useful Life (RUL) estimation.

Deliberately independent of app/ai/services/survival_service.py (the Weibull
AFT models used for warehouse-level report generation). This module never
imports it and never touches app/ai/models/survival_analysis/.

Method: for each component (tire, brake, battery, oil, hydraulic), fit a
simple linear trend of that asset's own sensor_readings health-percentage
history over time, then extrapolate forward to the day the trend crosses a
failure threshold. This is a per-asset statistical estimate computed fresh
from that asset's own data — not a population-trained ML model.

With fewer than two readings there's no trend to fit, so a single-point
estimate is returned instead (current health only, no history), and is
clearly flagged as low confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy import asc
from sqlalchemy.orm import Session

from app.models import Asset, SensorReading

FAILURE_THRESHOLD_PCT = 20.0
MIN_POINTS_FOR_TREND = 2

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
    estimated_failure_date: Optional[date]
    confidence: str  # "trend" | "single_point" | "no_data"
    readings_used: int


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Ordinary least squares slope/intercept for y = slope*x + intercept."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return 0.0, mean_y
    slope = num / den
    intercept = mean_y - slope * mean_x
    return slope, intercept


def _estimate_component(
    component: str,
    readings: list[tuple[datetime, Optional[float]]],
) -> ComponentRul:
    points = [(t, float(v)) for t, v in readings if v is not None]

    if not points:
        return ComponentRul(
            component=component,
            current_health_pct=None,
            degradation_pct_per_day=None,
            rul_days=None,
            estimated_failure_date=None,
            confidence="no_data",
            readings_used=0,
        )

    current_health = points[-1][1]

    if len(points) < MIN_POINTS_FOR_TREND:
        # Not enough history for a trend — fall back to a generic, clearly
        # low-confidence degradation assumption (0.05%/day, ~20 years to 20%
        # from 100%) so the UI still has *something* to show, honestly labelled.
        assumed_rate = 0.05
        rul_days = None
        if current_health > FAILURE_THRESHOLD_PCT:
            rul_days = int((current_health - FAILURE_THRESHOLD_PCT) / assumed_rate)
        return ComponentRul(
            component=component,
            current_health_pct=round(current_health, 1),
            degradation_pct_per_day=None,
            rul_days=rul_days,
            estimated_failure_date=(
                date.today().fromordinal(date.today().toordinal() + rul_days) if rul_days else None
            ),
            confidence="single_point",
            readings_used=len(points),
        )

    t0 = points[0][0]
    xs = [(t - t0).total_seconds() / 86400.0 for t, _ in points]
    ys = [v for _, v in points]
    slope, intercept = _linear_fit(xs, ys)

    # slope is %/day relative to t0; project from the LAST observed day forward.
    last_x = xs[-1]
    last_health = ys[-1]

    if slope >= 0:
        # Flat or improving trend (e.g. after a service) — no predictable
        # failure horizon from this data; report the trend but no RUL.
        return ComponentRul(
            component=component,
            current_health_pct=round(last_health, 1),
            degradation_pct_per_day=round(slope, 4),
            rul_days=None,
            estimated_failure_date=None,
            confidence="trend",
            readings_used=len(points),
        )

    days_to_threshold = (FAILURE_THRESHOLD_PCT - last_health) / slope  # slope < 0
    rul_days = max(0, int(days_to_threshold))

    return ComponentRul(
        component=component,
        current_health_pct=round(last_health, 1),
        degradation_pct_per_day=round(slope, 4),
        rul_days=rul_days,
        estimated_failure_date=date.today().fromordinal(date.today().toordinal() + rul_days),
        confidence="trend",
        readings_used=len(points),
    )


def compute_asset_component_rul(db: Session, asset_id: str) -> list[ComponentRul]:
    """Return a per-component RUL estimate for one asset, computed from that
    asset's own sensor_readings history. Raises ValueError if the asset
    doesn't exist."""
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

    return results
