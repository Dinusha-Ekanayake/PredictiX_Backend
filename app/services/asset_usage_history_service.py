"""Per-asset operating history read straight from stored sensor readings.

Backs the asset section's utilisation and service-cadence charts. Every value
returned here is a recorded measurement: nothing is fitted, extrapolated or
predicted, so a point on these charts is only ever something the asset
actually did.

Readings are stored one row per month per asset. They are returned oldest
first so a caller can plot them left to right without re-sorting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models import SensorReading

# How many months a caller gets when it does not ask for a specific window.
# Two years is long enough to show a service rhythm and several seasons while
# still leaving each point wide enough to read in a panel-sized chart.
DEFAULT_MONTHS = 24

# Upper bound on the window. The fleet stores 61 monthly readings per asset,
# so this covers the longest history that exists and stops a caller asking
# for an unbounded range.
MAX_MONTHS = 120


@dataclass
class UsagePoint:
    """One month of recorded operation for a single asset."""

    period: date
    operating_hours: Optional[float]
    idle_hours: Optional[float]
    distance_km: Optional[float]
    days_since_last_service: Optional[int]
    downtime_hours_90d: Optional[float]


def _to_float(value) -> Optional[float]:
    """Round a stored numeric to one decimal, or None when it is absent.

    Readings arrive as Decimal from Postgres. Rounding here keeps the JSON
    small and stops a chart axis rendering values to full float precision.
    """
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_asset_usage_history(
    db: Session, asset_id: str, months: int = DEFAULT_MONTHS
) -> list[UsagePoint]:
    """The most recent `months` readings for one asset, oldest first.

    Returns an empty list when the asset has no readings. That is a normal
    state for an asset added but not yet reporting, so it is not an error.
    """
    months = max(1, min(int(months), MAX_MONTHS))

    # Newest first with a limit, so the database returns only the window
    # asked for rather than the asset's whole history.
    rows = (
        db.query(
            SensorReading.recorded_at,
            SensorReading.operating_hours_last_30d,
            SensorReading.idle_hours_last_30d,
            SensorReading.distance_last_30d_km,
            SensorReading.days_since_last_service,
            SensorReading.downtime_hours_last_90d,
        )
        .filter(SensorReading.asset_id == asset_id)
        .order_by(SensorReading.recorded_at.desc())
        .limit(months)
        .all()
    )

    points = [
        UsagePoint(
            period=r.recorded_at.date() if hasattr(r.recorded_at, "date") else r.recorded_at,
            operating_hours=_to_float(r.operating_hours_last_30d),
            idle_hours=_to_float(r.idle_hours_last_30d),
            distance_km=_to_float(r.distance_last_30d_km),
            days_since_last_service=_to_int(r.days_since_last_service),
            downtime_hours_90d=_to_float(r.downtime_hours_last_90d),
        )
        for r in rows
        if r.recorded_at is not None
    ]

    points.reverse()
    return points
