"""
AI Services module for PredictiX API.

All four services call the HuggingFace Inference API directly over HTTP
(see ``_hf_inference.py``). No model weights are downloaded locally.
"""

from app.ai.services.asset_summary_service import (
    generate_asset_summary,
    get_asset_summary_repo,
)

from app.ai.services.ticket_categorization_service import (
    categorize_ticket_text,
    get_ticket_categorizer_repo,
    warmup_ticket_categorizer,
)

from app.ai.services.ticket_priority_service import (
    predict_ticket_priority,
    warmup_ticket_priority,
)

from app.ai.services.ticket_summary_service import (
    build_ticket_summary_input,
    generate_ticket_summary,
    get_ticket_summary_repo,
)

__all__ = [
    # Asset summary (served on a HF Space)
    "generate_asset_summary",
    "get_asset_summary_repo",
    # Ticket categorization
    "categorize_ticket_text",
    "get_ticket_categorizer_repo",
    "warmup_ticket_categorizer",
    # Ticket priority (user-tickets section)
    "predict_ticket_priority",
    "warmup_ticket_priority",
    # Ticket summary (served on a HF Space)
    "generate_ticket_summary",
    "build_ticket_summary_input",
    "get_ticket_summary_repo",
]
