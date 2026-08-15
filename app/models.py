from sqlalchemy import Column, String, Text, Integer, Boolean, Date, DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import ENUM, UUID, JSONB
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db import Base
import uuid

# Postgres ENUM types already defined in the DB. `create_type=False` tells
# SQLAlchemy "this enum already exists, don't try to CREATE TYPE it".
TicketStatusEnum = ENUM(
    "open", "in_progress", "pending", "resolved", "closed", "cancelled",
    name="ticket_status", create_type=False,
)
TicketPriorityEnum = ENUM(
    "low", "medium", "high",
    name="ticket_priority", create_type=False,
)
TicketCategoryEnum = ENUM(
    "electrical", "mechanical", "software",
    name="ticket_category", create_type=False,
)


class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(Text, unique=True, nullable=False)
    name = Column(Text, nullable=False)
    address = Column(Text)
    city = Column(Text)
    district = Column(Text)
    country = Column(Text, default="Sri Lanka")
    timezone = Column(Text, default="Asia/Colombo")
    is_active = Column(Boolean, default=True)
    climate_zone = Column(Text)
    warehouse_type = Column(Text)
    # DB column is "metadata" ("meta" attr avoids clashing with Base.metadata)
    meta = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Department(Base):
    __tablename__ = "departments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    code = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(UUID(as_uuid=True), primary_key=True)
    employee_id = Column(Text, unique=True)
    full_name = Column(Text, nullable=False)
    email = Column(Text, unique=True)
    phone = Column(Text)
    role = Column(Text, nullable=False, default="user")
    status = Column(Text, nullable=False, default="active")
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"))
    avatar_url = Column(Text)
    meta = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_code = Column(Text, unique=True, nullable=False)
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"))
    asset_name = Column(Text, nullable=False)
    asset_type = Column(Text, nullable=False, default="vehicle")
    category = Column(Text)
    vehicle_type = Column(Text)
    make = Column(Text)
    model = Column(Text)
    manufacture_year = Column(Integer)
    registration_number = Column(Text)
    vin = Column(Text, unique=True)
    # Warehouse parking bay, "<zone>-<bay>" e.g. "A-012". Unique per warehouse
    # (partial unique index, see docs/migrations/009_*.sql); NULL = unassigned.
    parking_slot = Column(Text)
    status = Column(Text, nullable=False, default="active")
    health_band = Column(Text)
    criticality_score = Column(Numeric(5, 2))
    purchase_date = Column(Date)
    warranty_expiry_date = Column(Date)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    current_mileage = Column(Numeric(12, 2))
    last_service_date = Column(Date)
    next_service_date = Column(Date)
    description = Column(Text)
    fuel_type = Column(Text)
    transmission = Column(Text)
    make_model = Column(Text)
    maintenance_priority = Column(Text)
    service_provider_type = Column(Text)
    # DB column is "metadata" ("meta" attr avoids clashing with Base.metadata)
    meta = Column("metadata", JSONB, default={})
    created_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    vehicle_role = Column(Text)
    payload_capacity_kg = Column(Numeric(12, 2))
    vehicle_age_years = Column(Integer)
    lifetime_service_count = Column(Integer)
    lifetime_breakdown_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MaintenanceEvent(Base):
    __tablename__ = "maintenance_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    event_type = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text)
    performed_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    scheduled_date = Column(DateTime(timezone=True))
    performed_at = Column(DateTime(timezone=True))
    odometer_reading = Column(Numeric(12, 2))
    downtime_hours = Column(Numeric(10, 2))
    cost_amount = Column(Numeric(12, 2))
    currency = Column(Text, default="LKR")
    vendor_name = Column(Text)
    notes = Column(Text)
    # DB column is "metadata" ("meta" attr avoids clashing with Base.metadata)
    meta = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())

    temperature = Column(Numeric(10, 3))
    vibration = Column(Numeric(10, 3))
    pressure = Column(Numeric(10, 3))
    humidity = Column(Numeric(10, 3))
    rpm = Column(Numeric(10, 3))
    voltage = Column(Numeric(10, 3))
    fuel_level = Column(Numeric(10, 3))
    odometer = Column(Numeric(12, 2))

    engine_hours_since_last_service = Column(Numeric(12, 2))
    days_since_last_service = Column(Integer)
    tire_health_pct = Column(Numeric(10, 2))
    brake_health_pct = Column(Numeric(10, 2))
    mileage_since_last_service_km = Column(Numeric(12, 2))
    battery_health_pct = Column(Numeric(10, 2))
    oil_life_pct = Column(Numeric(10, 2))
    hydraulic_health_pct = Column(Numeric(10, 2))
    vibration_rms_mm_s = Column(Numeric(10, 3))
    fuel_price_lkr_per_l = Column(Numeric(12, 2))
    engine_hours_total = Column(Numeric(12, 2))
    coolant_temp_max_c = Column(Numeric(10, 2))
    engine_temp_avg_c = Column(Numeric(10, 2))
    battery_voltage_v = Column(Numeric(10, 3))
    odometer_km = Column(Numeric(12, 2))
    downtime_hours_last_90d = Column(Numeric(10, 2))
    active_fault_code_count = Column(Integer)
    distance_last_30d_km = Column(Numeric(12, 2))
    payload_utilization_pct = Column(Numeric(10, 2))
    trip_count_30d = Column(Integer)
    ambient_humidity_avg_pct = Column(Numeric(10, 2))
    rough_road_pct = Column(Numeric(10, 2))
    idle_hours_last_30d = Column(Numeric(12, 2))
    port_route_pct = Column(Numeric(10, 2))
    overload_events_30d = Column(Integer)
    fuel_rate_lph = Column(Numeric(10, 3))
    avg_payload_kg = Column(Numeric(12, 2))

    ambient_temp_avg_c = Column(Numeric(10, 2))
    avg_trip_distance_km = Column(Numeric(12, 2))
    cargo_type = Column(Text)
    fuel_efficiency_km_per_l = Column(Numeric(10, 3))
    is_home_warehouse_service = Column(Boolean)
    last_service_type = Column(Text)
    maintenance_cost_last_service_lkr = Column(Numeric(12, 2))
    major_component_replaced = Column(Text)
    operating_hours_last_30d = Column(Numeric(12, 2))
    operating_shift = Column(Text)
    parts_replaced_last_service = Column(Text)
    rainfall_mm_30d = Column(Numeric(12, 2))
    route_type = Column(Text)
    sensor_fault_flag = Column(Boolean)
    start_stop_burden_30d = Column(Integer)
    tire_pressure_psi = Column(Numeric(10, 2))
    urban_route_pct = Column(Numeric(10, 2))

    reading_payload = Column(JSONB, default={})


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_number = Column(Text, unique=True, nullable=False)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"))
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    # These six columns are Postgres ENUMs in the DB, not text — see top of
    # file for the ENUM type definitions.
    status = Column(TicketStatusEnum, nullable=False, default="open")
    priority = Column(TicketPriorityEnum)
    predicted_priority = Column(TicketPriorityEnum)
    final_priority = Column(TicketPriorityEnum)
    predicted_category = Column(TicketCategoryEnum)
    final_category = Column(TicketCategoryEnum)
    ticket_summary = Column(Text)
    asset_summary = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    # DB column is `metadata` but the Python attribute stays `meta` so existing
    # callers (admin code, partner work) keep working unchanged, and to avoid
    # clashing with SQLAlchemy's Base.metadata.
    meta = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PredictionRun(Base):
    __tablename__ = "prediction_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id = Column(UUID(as_uuid=True), ForeignKey("model_registry.id"), nullable=False)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=True)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=True)
    input_snapshot = Column(JSONB, nullable=False, default={})
    requested_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    run_started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    run_finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False, default="completed")
    error_message = Column(Text, nullable=True)

class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_type = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending")
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"))
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"))
    title = Column(Text, nullable=False)
    generated_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    report_text = Column(Text)
    report_json = Column(JSONB, default={})
    file_path = Column(Text)
    generation_started_at = Column(DateTime(timezone=True), server_default=func.now())
    generation_completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    type = Column(Text, nullable=False)
    channel = Column(Text, nullable=False, default="in_app")
    title = Column(Text, nullable=False)
    message = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="unread")
    related_asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"))
    related_ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"))
    related_report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id"))
    sent_at = Column(DateTime(timezone=True))
    read_at = Column(DateTime(timezone=True))
    # DB column is "metadata" ("meta" attr avoids clashing with Base.metadata)
    meta = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AssetAssignment(Base):
    __tablename__ = "asset_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False, index=True)
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    unassigned_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    notes = Column(Text)


class AssetStatusHistory(Base):
    __tablename__ = "asset_status_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False, index=True)
    old_status = Column(Text)
    new_status = Column(Text, nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AssetDocument(Base):
    __tablename__ = "asset_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False, index=True)
    title = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    mime_type = Column(Text)
    document_type = Column(Text)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    # DB column is "metadata" ("meta" attr avoids clashing with Base.metadata)
    meta = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    comment = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    file_path = Column(Text, nullable=False)
    mime_type = Column(Text)
    original_filename = Column(Text)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TicketStatusHistory(Base):
    __tablename__ = "ticket_status_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    old_status = Column(Text)
    new_status = Column(Text, nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_name = Column(Text, nullable=False)
    model_type = Column(Text, nullable=False)
    version = Column(Text, nullable=False)
    framework = Column(Text)
    artifact_path = Column(Text)
    metrics = Column(JSONB, default={})
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AssetFailurePrediction(Base):
    __tablename__ = "asset_failure_predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("prediction_runs.id"), unique=True, nullable=False)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    health_score = Column(Numeric(10, 4))
    failure_probability = Column(Numeric(10, 4))
    confidence = Column(Numeric(10, 4))
    risk_level = Column(Text)
    predicted_maintenance_date = Column(Date)
    days_until_maintenance = Column(Integer)
    top_explanations = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AssetCostPrediction(Base):
    __tablename__ = "asset_cost_predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("prediction_runs.id"), unique=True, nullable=False)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    estimated_cost = Column(Numeric(12, 2))
    min_cost = Column(Numeric(12, 2))
    max_cost = Column(Numeric(12, 2))
    currency = Column(Text, default="LKR")
    confidence_score = Column(Numeric(10, 4))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class TicketPrediction(Base):
    __tablename__ = "ticket_predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("prediction_runs.id"), unique=True, nullable=False)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False, index=True)

    predicted_category = Column(Text, nullable=True)
    predicted_priority = Column(Text, nullable=True)
    category_confidence = Column(Numeric(10, 4), nullable=True)
    priority_confidence = Column(Numeric(10, 4), nullable=True)
    generated_summary = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PredictionExplanation(Base):
    __tablename__ = "prediction_explanations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("prediction_runs.id"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), index=True)
    explanation_type = Column(Text, nullable=False, default="shap")
    explanation_text = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PredictionFeatureImportance(Base):
    __tablename__ = "prediction_feature_importance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    explanation_id = Column(UUID(as_uuid=True), ForeignKey("prediction_explanations.id"), nullable=False)
    feature_name = Column(Text, nullable=False)
    feature_value = Column(Text)
    importance_score = Column(Numeric(16, 8), nullable=False)
    direction = Column(Text)
    rank_order = Column(Integer)


class ReportSource(Base):
    __tablename__ = "report_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id"), nullable=False)
    source_table = Column(Text, nullable=False)
    source_id = Column(UUID(as_uuid=True))
    source_label = Column(Text)
    relevance_score = Column(Numeric(10, 4))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserNotificationPreference(Base):
    __tablename__ = "user_notification_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    channel = Column(Text, nullable=False)
    notification_type = Column(Text, nullable=False)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PdmBatchPrediction(Base):
    """One row per asset — upserted by the hourly batch PDM scheduler."""

    __tablename__ = "pdm_batch_predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, unique=True)

    failure_probability = Column(Numeric(10, 4))
    maintenance_required = Column(Boolean)
    risk_level = Column(Text)

    predicted_days_until_maintenance = Column(Integer)
    predicted_maintenance_date = Column(Date)

    health_score = Column(Numeric(10, 4))
    health_status = Column(Text)
    contributing_factors = Column(JSONB, default=[])

    estimated_cost_lkr = Column(Numeric(12, 2))
    min_cost_lkr = Column(Numeric(12, 2))
    max_cost_lkr = Column(Numeric(12, 2))

    top_explanations = Column(JSONB, default=[])

    predicted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    run_duration_ms = Column(Integer)
    error_message = Column(Text)
    status = Column(Text, nullable=False, default="ok")

    # Auditability — which model generation + exact input produced this row.
    model_version = Column(Text)
    feature_snapshot = Column(JSONB, default={})

    # Decision layer (app.ai.services.pdm_decision_service.build_decision).
    tier = Column(Text)
    agreement = Column(Boolean)
    display_mode = Column(Text)
    horizon_text = Column(Text)
    recommended_action = Column(Text)
    horizon_saturated = Column(Boolean, default=False)


class PdmPredictionHistory(Base):
    """Append-only log of every batch prediction run — never upserted or
    overwritten, unlike PdmBatchPrediction (which only ever holds the latest
    row per asset).

    Exists so that predictions made today can eventually be checked against
    what actually happened afterward (a real maintenance_event within N days,
    an unplanned "repair" event, etc.) — the validation this system currently
    cannot do because PdmBatchPrediction discards prior predictions on every
    upsert. One row is inserted per asset per batch run; nothing here is ever
    updated or deleted by the app itself.
    """
    __tablename__ = "pdm_prediction_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)

    failure_probability = Column(Numeric(10, 4))
    predicted_days_until_maintenance = Column(Integer)
    predicted_maintenance_date = Column(Date)
    health_score = Column(Numeric(10, 4))
    tier = Column(Text)
    model_version = Column(Text)

    predicted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ServiceReminderLog(Base):
    """One row per service-reminder email send attempt."""
    __tablename__ = "service_reminder_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    asset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    service_date = Column(Date, nullable=False)
    reminder_offset_days = Column(Integer, nullable=False)

    trigger = Column(String, nullable=False)
    sent_by = Column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    email_to = Column(String, nullable=False)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)

    sent_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())