"""Pydantic response schemas for the FRSO survival endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Component = Literal["brake", "tire", "battery", "oil", "hydraulic"]


class SurvivalCurvePoint(BaseModel):
    day: int = Field(..., description="Days from now")
    survival_prob: float = Field(..., ge=0.0, le=1.0, description="P(component survives ≥ this day)")


class ComponentSurvivalResponse(BaseModel):
    asset_id: str
    component: Component
    median_days: float = Field(..., description="p50 — 50% chance component fails by this day")
    p10_days:    float = Field(..., description="p10 — 90% chance component survives past this day")
    p90_days:    float = Field(..., description="p90 — only 10% chance component survives past this day")
    curve: list[SurvivalCurvePoint]


class ComponentSurvivalError(BaseModel):
    component: Component
    error: str


class AssetSurvivalResponse(BaseModel):
    asset_id: str
    horizon_days: int
    step_days: int
    soonest_component: Component | None = Field(
        None, description="Component with the lowest predicted median failure time"
    )
    soonest_median_days: float | None
    components: list[ComponentSurvivalResponse | ComponentSurvivalError]
