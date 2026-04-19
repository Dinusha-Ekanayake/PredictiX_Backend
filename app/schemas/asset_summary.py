from typing import Optional
from pydantic import BaseModel


class AssetSummaryRequest(BaseModel):
    """Request schema for asset summary generation"""
    input_text: str

    class Config:
        json_schema_extra = {
            "example": {
                "input_text": "Vehicle: SLW0225 | Type: Light Truck 3.5T | Model: Mitsubishi Canter | Component health: oil 93.5%, brakes 79.7%, tires 58.7%, battery 66.3%, hydraulics 62.5%"
            }
        }


class AssetSummaryResponse(BaseModel):
    """Response schema for generated summary"""
    summary: str
    generated_at: str
    model_version: str = "1.0"

    class Config:
        json_schema_extra = {
            "example": {
                "summary": "Light Truck 3.5T SLW0225 (Mitsubishi Canter) requires tire service within 30 days. Component health: oil 93.5%, brakes 79.7%, tires 58.7%, battery 66.3%, hydraulics 62.5%",
                "generated_at": "2026-04-18T10:30:45.123456",
                "model_version": "1.0"
            }
        }
