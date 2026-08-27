"""Response schema for the per-asset operating history endpoint.

Every field is a recorded measurement. Any of them may be null for a given
month when that reading did not carry the value, so the client is expected to
skip a null rather than treat it as zero.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class UsagePointOut(BaseModel):
    period: date
    operating_hours: Optional[float] = None
    idle_hours: Optional[float] = None
    distance_km: Optional[float] = None
    days_since_last_service: Optional[int] = None
    downtime_hours_90d: Optional[float] = None


class AssetUsageHistoryResponse(BaseModel):
    asset_id: str
    months: int
    points: list[UsagePointOut]
