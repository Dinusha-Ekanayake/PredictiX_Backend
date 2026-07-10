"""Response schema for the per-asset component RUL endpoint.

Independent of app/schemas/survival.py (report-generation Weibull models).
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel


Confidence = Literal["trend", "insufficient_trend", "single_point", "no_data"]


class ComponentRulOut(BaseModel):
    component: str
    current_health_pct: Optional[float] = None
    degradation_pct_per_day: Optional[float] = None
    rul_days: Optional[int] = None
    rul_days_low: Optional[int] = None
    rul_days_high: Optional[int] = None
    estimated_failure_date: Optional[date] = None
    confidence: Confidence
    readings_used: int
    # Model-grounding (see asset_component_rul_service._apply_model_grounding):
    # cross-checks this component's own 4-point OLS trend against the v7
    # regressor's whole-asset prediction instead of trusting the trend alone.
    horizon_capped: bool = False
    model_corroborated: bool = False
    model_days_ceiling: Optional[int] = None
    disagrees_with_model: bool = False


class AssetComponentRulResponse(BaseModel):
    asset_id: str
    components: list[ComponentRulOut]
