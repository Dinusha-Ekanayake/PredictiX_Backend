from typing import Optional
from pydantic import BaseModel


class TicketSummaryRequest(BaseModel):
    """Request schema for ticket summary generation.

    Provide the structured ticket fields (preferred) or a pre-formatted
    `input_text`; if `input_text` is given it takes precedence.
    """
    title: str = ""
    description: str = ""
    asset_name: Optional[str] = None
    asset_code: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    input_text: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Brake fluid contamination",
                "description": "Electric Pallet Jack AS-071 reported brake fluid contamination. Status: Resolved.",
                "asset_code": "AS-071",
                "category": "Brake System",
                "priority": "Low",
            }
        }


class TicketSummaryResponse(BaseModel):
    """Response schema for a generated ticket summary."""
    summary: str
    generated_at: str
    model_version: str = "1.0"
