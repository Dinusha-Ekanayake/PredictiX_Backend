"""Response schema for the per-asset component RUL endpoint.

Independent of app/schemas/survival.py (report-generation Weibull models).
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel


Confidence = Literal["trend", "single_point", "no_data"]


class ComponentRulOut(BaseModel):
    component: str
    current_health_pct: Optional[float] = None
    degradation_pct_per_day: Optional[float] = None
    rul_days: Optional[int] = None
    estimated_failure_date: Optional[date] = None
    confidence: Confidence
    readings_used: int


class AssetComponentRulResponse(BaseModel):
    asset_id: str
    components: list[ComponentRulOut]
