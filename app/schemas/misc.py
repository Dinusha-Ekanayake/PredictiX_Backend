from pydantic import BaseModel
from uuid import UUID
from typing import Optional, Any, Literal
from datetime import datetime
from decimal import Decimal


class AssetAssignmentCreate(BaseModel):
    asset_id: UUID
    user_id: UUID
    assigned_by: Optional[UUID] = None
    assigned_at: Optional[datetime] = None
    unassigned_at: Optional[datetime] = None
    is_active: bool = True
    notes: Optional[str] = None


class AssetAssignmentOut(AssetAssignmentCreate):
    id: UUID

    # Resolved on the way out so the assignment history reads as names rather
    # than as UUIDs. Optional because a referenced profile may since have been
    # deleted, in which case the id is still returned and the name is absent.
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    assigned_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class AssetStatusHistoryCreate(BaseModel):
    asset_id: UUID
    old_status: Optional[str] = None
    new_status: str
    changed_by: Optional[UUID] = None
    reason: Optional[str] = None


class AssetStatusHistoryOut(AssetStatusHistoryCreate):
    id: UUID

    class Config:
        from_attributes = True


class AssetDocumentCreate(BaseModel):
    asset_id: UUID
    title: str
    file_path: str
    mime_type: Optional[str] = None
    document_type: Optional[str] = None
    uploaded_by: Optional[UUID] = None
    # Maps to the ORM attribute `AssetDocument.meta` (DB column "metadata").
    # Must NOT be named `metadata` here, or Pydantic's from_attributes reads
    # SQLAlchemy's reserved MetaData object instead of the JSONB value.
    meta: Optional[Any] = None


class AssetDocumentOut(AssetDocumentCreate):
    id: UUID

    class Config:
        from_attributes = True


class TicketCommentCreate(BaseModel):
    ticket_id: UUID
    user_id: UUID
    comment: str
    is_internal: bool = False


class TicketCommentOut(TicketCommentCreate):
    id: UUID
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TicketAttachmentCreate(BaseModel):
    ticket_id: UUID
    file_path: str
    mime_type: Optional[str] = None
    original_filename: Optional[str] = None
    uploaded_by: Optional[UUID] = None


class TicketAttachmentOut(TicketAttachmentCreate):
    id: UUID
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TicketStatusHistoryCreate(BaseModel):
    ticket_id: UUID
    old_status: Optional[str] = None
    new_status: str
    changed_by: Optional[UUID] = None
    note: Optional[str] = None


class TicketStatusHistoryOut(TicketStatusHistoryCreate):
    id: UUID
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ModelRegistryCreate(BaseModel):
    model_name: str
    model_type: str
    version: str
    framework: Optional[str] = None
    artifact_path: Optional[str] = None
    metrics: Optional[Any] = None
    is_active: bool = True


class ModelRegistryOut(ModelRegistryCreate):
    id: UUID

    class Config:
        from_attributes = True


class PredictionExplanationCreate(BaseModel):
    run_id: UUID
    asset_id: Optional[UUID] = None
    explanation_type: str = "shap"
    explanation_text: Optional[str] = None


class PredictionExplanationOut(PredictionExplanationCreate):
    id: UUID

    class Config:
        from_attributes = True


class PredictionFeatureImportanceCreate(BaseModel):
    explanation_id: UUID
    feature_name: str
    feature_value: Optional[str] = None
    importance_score: Decimal
    direction: Optional[str] = None
    rank_order: Optional[int] = None


class PredictionFeatureImportanceOut(PredictionFeatureImportanceCreate):
    id: UUID

    class Config:
        from_attributes = True


class ReportSourceCreate(BaseModel):
    report_id: UUID
    source_table: str
    source_id: Optional[UUID] = None
    source_label: Optional[str] = None
    relevance_score: Optional[Decimal] = None


class ReportSourceOut(ReportSourceCreate):
    id: UUID

    class Config:
        from_attributes = True


# Both columns are Postgres enums. Typing them as plain `str` let any value
# through Pydantic and pushed the rejection down to the INSERT, where an
# unknown value surfaced as a psycopg2 InvalidTextRepresentation — a 500 with
# a raw SQL traceback for what is really a client input error. Constraining
# them here turns that into a 422 that names the valid options.
NotificationChannel = Literal["in_app", "email"]
NotificationType = Literal[
    "high_risk_asset", "ticket_created", "ticket_resolved", "ticket_updated",
    "maintenance_due", "prediction_ready", "report_ready", "system",
]


class UserNotificationPreferenceCreate(BaseModel):
    user_id: UUID
    channel: NotificationChannel
    notification_type: NotificationType
    enabled: bool = True


class UserNotificationPreferenceOut(UserNotificationPreferenceCreate):
    id: UUID

    class Config:
        from_attributes = True