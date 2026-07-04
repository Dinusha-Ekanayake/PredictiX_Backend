"""Tool definitions for the PredictiX chatbot agent (v2: agentic db access)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel

from app.db.supabase_client import supabase

log = logging.getLogger("predictix.agent.tools")

@dataclass
class ToolContext:
    """Per-request context handed to every tool handler."""
    db: Optional[Session]
    user: Any  # Profile or MockProfile

    @property
    def is_admin(self) -> bool:
        # super_admin has the same admin capabilities as admin.
        return str(getattr(self.user, "role", "")).lower() in ("admin", "super_admin")

    @property
    def user_id(self) -> str:
        return str(getattr(self.user, "id", ""))

def _require_db(ctx: ToolContext) -> Session:
    if ctx.db is None:
        raise RuntimeError("Database is not configured for this request.")
    return ctx.db

# ─── Schema definitions for the sub-agent ─────────────────────────────────────
DB_SCHEMAS = {
    "warehouses": "id, code, name, address, city, district, country, timezone, is_active, climate_zone, warehouse_type, metadata, created_at, updated_at",
    "departments": "id, warehouse_id, code, name, description, is_active, created_at, updated_at",
    "profiles": "id, employee_id, full_name, email, phone, role, status, warehouse_id, department_id, avatar_url, meta, created_at, updated_at",
    "assets": "id, asset_code, warehouse_id, department_id, asset_name, asset_type, category, vehicle_type, make, model, manufacture_year, registration_number, vin, status, health_band, criticality_score, purchase_date, warranty_expiry_date, assigned_to, current_mileage, last_service_date, next_service_date, description, fuel_type, transmission, make_model, maintenance_priority, service_provider_type, metadata, created_by, vehicle_role, payload_capacity_kg, vehicle_age_years, lifetime_service_count, lifetime_breakdown_count, created_at, updated_at",
    "maintenance_events": "id, asset_id, event_type, title, description, performed_by, scheduled_date, performed_at, odometer_reading, downtime_hours, cost_amount, currency, vendor_name, notes, metadata, created_at, updated_at",
    "sensor_readings": "id, asset_id, recorded_at, temperature, vibration, pressure, humidity, rpm, voltage, fuel_level, odometer, engine_hours_since_last_service, days_since_last_service, tire_health_pct, brake_health_pct, mileage_since_last_service_km, battery_health_pct, oil_life_pct, hydraulic_health_pct, vibration_rms_mm_s, fuel_price_lkr_per_l, engine_hours_total, coolant_temp_max_c, engine_temp_avg_c, battery_voltage_v, odometer_km, downtime_hours_last_90d, active_fault_code_count, distance_last_30d_km, payload_utilization_pct, trip_count_30d, ambient_humidity_avg_pct, rough_road_pct, idle_hours_last_30d, port_route_pct, overload_events_30d, fuel_rate_lph, avg_payload_kg, ambient_temp_avg_c, avg_trip_distance_km, cargo_type, fuel_efficiency_km_per_l, is_home_warehouse_service, last_service_type, maintenance_cost_last_service_lkr, major_component_replaced, operating_hours_last_30d, operating_shift, parts_replaced_last_service, rainfall_mm_30d, route_type, sensor_fault_flag, start_stop_burden_30d, tire_pressure_psi, urban_route_pct, reading_payload",
    "tickets": "id, ticket_number, asset_id, warehouse_id, title, description, status(open, in_progress, pending, resolved, closed, cancelled), priority(low, medium, high), predicted_priority, final_priority, predicted_category(electrical, mechanical, software), final_category, ticket_summary, asset_summary, created_by, assigned_to, reviewed_by, opened_at, reviewed_at, resolved_at, closed_at, metadata, created_at, updated_at",
    "prediction_runs": "id, model_id, asset_id, ticket_id, input_snapshot, requested_by, run_started_at, run_finished_at, status, error_message",
    "reports": "id, report_type, status, asset_id, warehouse_id, ticket_id, title, generated_by, report_text, report_json, file_path, generation_started_at, generation_completed_at, created_at, updated_at",
    "notifications": "id, user_id, type, channel, title, message, status, related_asset_id, related_ticket_id, related_report_id, sent_at, read_at, metadata, created_at",
    "asset_assignments": "id, asset_id, user_id, assigned_by, assigned_at, unassigned_at, is_active, notes",
    "asset_status_history": "id, asset_id, old_status, new_status, changed_by, reason, created_at",
    "asset_documents": "id, asset_id, title, file_path, mime_type, document_type, uploaded_by, metadata, created_at",
    "ticket_comments": "id, ticket_id, user_id, comment, is_internal, created_at",
    "ticket_attachments": "id, ticket_id, file_path, mime_type, original_filename, uploaded_by, created_at",
    "ticket_status_history": "id, ticket_id, old_status, new_status, changed_by, note, created_at",
    "model_registry": "id, model_name, model_type, version, framework, artifact_path, metrics, is_active, created_at",
    "asset_failure_predictions": "id, run_id, asset_id, health_score, failure_probability, confidence, risk_level, predicted_maintenance_date, days_until_maintenance, top_explanations, created_at",
    "asset_cost_predictions": "id, run_id, asset_id, estimated_cost, min_cost, max_cost, currency, confidence_score, created_at",
    "ticket_predictions": "id, run_id, ticket_id, predicted_category, predicted_priority, category_confidence, priority_confidence, generated_summary, created_at",
    "prediction_explanations": "id, run_id, asset_id, explanation_type, explanation_text, created_at",
    "prediction_feature_importance": "id, explanation_id, feature_name, feature_value, importance_score, direction, rank_order",
    "report_sources": "id, report_id, source_table, source_id, source_label, relevance_score, created_at",
    "user_notification_preferences": "id, user_id, channel, notification_type, enabled, created_at, updated_at",
    "pdm_batch_predictions": "id, asset_id, failure_probability, maintenance_required, risk_level, predicted_days_until_maintenance, predicted_maintenance_date, health_score, health_status, contributing_factors, estimated_cost_lkr, min_cost_lkr, max_cost_lkr, top_explanations, predicted_at, run_duration_ms, error_message, status",
}

def _tool_supabase_access(args: dict, ctx: ToolContext) -> dict:
    """Uses the database sub-agent to execute a safe read-only SQL query."""
    from app.ai.agent.agent_service import get_sql_from_subagent
    
    tables = args.get("tables", [])
    instruction = args.get("instruction", "")
    if not tables or not instruction:
        return {"error": "tables and instruction are required."}

    # Gather schema only for the requested tables
    schema_details = []
    for t in tables:
        if t in DB_SCHEMAS:
            schema_details.append(f"Table '{t}': {DB_SCHEMAS[t]}")
        else:
            schema_details.append(f"Table '{t}': Unknown table")
    
    schema_str = "\\n".join(schema_details)
    
    # 1. Ask the sub-agent to write the SQL query
    sql_query = get_sql_from_subagent(instruction, schema_str)
    
    if "ERROR:" in sql_query:
        return {"error": sql_query}
        
    # Security: Ensure it's read-only
    if any(kw in sql_query.upper() for kw in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]):
        return {"error": "Only SELECT queries are allowed."}

    # 2. Execute the query
    db = _require_db(ctx)
    try:
        # Enforce scope if non-admin
        # We'll rely on the sub-agent being told about the current_user_id
        result = db.execute(text(sql_query)).fetchall()
        
        # Convert rows to dict
        keys = result[0]._mapping.keys() if result else []
        rows = [dict(zip(keys, row)) for row in result]
        return {"sql_executed": sql_query, "results": rows[:50]} # Cap at 50 rows
    except Exception as e:
        return {"error": f"SQL execution failed: {e}", "sql_attempted": sql_query}


def _tool_list_faqs(args: dict, ctx: ToolContext) -> dict:
    search = (args.get("search") or "").strip().lower()
    response = (
        supabase.from_("faqs")
        .select("id,question,answer,category")
        .eq("is_active", True)
        .order("created_at", desc=True)
        .execute()
    )
    rows = response.data or []
    if search:
        rows = [r for r in rows if search in r["question"].lower() or search in r["answer"].lower()]
    rows = rows[: int(args.get("limit", 5))]
    return {"count": len(rows), "faqs": rows}


def _tool_search_knowledge(args: dict, ctx: ToolContext) -> dict:
    from app.ai.services.knowledge_service import search_knowledge
    query = args.get("query", "").strip()
    if not query:
        return {"error": "query is required"}
    results = search_knowledge(query, match_count=int(args.get("match_count", 3)))
    return {"count": len(results), "results": results}


def _tool_whoami(args: dict, ctx: ToolContext) -> dict:
    """Return basic info about the current user."""
    return {
        "id": ctx.user_id,
        "email": getattr(ctx.user, "email", None),
        "role": getattr(ctx.user, "role", "user"),
        "full_name": getattr(ctx.user, "full_name", None),
        "department_id": str(ctx.user.department_id) if getattr(ctx.user, "department_id", None) else None,
        "warehouse_id": str(ctx.user.warehouse_id) if getattr(ctx.user, "warehouse_id", None) else None,
    }


def _tool_mr_guideline_helper(args: dict, ctx: ToolContext) -> dict:
    """Return system navigation guidelines for Mr. Guideline Helper."""
    question = args.get("question", "").lower()
    
    # Generic helpdesk/navigation instructions
    guidelines = "Mr. Guideline Helper says:\\n"
    if "password" in question:
        guidelines += "To change your password, click on your profile avatar in the top right corner, go to 'Profile Settings', and select 'Change Password'.\\n"
    elif "helpdesk" in question or "ticket" in question:
        guidelines += "To access the Helpdesk and manage tickets, click on 'Helpdesk' in the main navigation sidebar.\\n"
    elif "asset" in question:
        guidelines += "To view or manage assets, click on 'Assets' in the main navigation sidebar.\\n"
    elif "report" in question:
        guidelines += "To generate reports, click on 'Reports' in the main navigation sidebar.\\n"
    else:
        guidelines += "You can navigate the system using the sidebar on the left. You'll find sections for Dashboard, Assets, Helpdesk, Reports, and Settings.\\n"
        
    guidelines += "\\nPlease visit the Helpdesk section for more details. If you need further support, contact the admin at neuromindspredictix@gmail.com."
    
    return {"guideline": guidelines}


# ─── Tool registry ────────────────────────────────────────────────────────────

TOOL_HANDLERS: dict[str, Callable[[dict, ToolContext], Any]] = {
    "whoami": _tool_whoami,
    "supabase_access": _tool_supabase_access,
    "list_faqs": _tool_list_faqs,
    "search_knowledge": _tool_search_knowledge,
    "mr_guideline_helper": _tool_mr_guideline_helper,
}

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "whoami",
            "description": "Return information about the currently logged-in user (id, email, role, department). Call this first when you need to know who you're helping.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "supabase_access",
            "description": "Execute a database query against Supabase to get real data. Use this for ANY question about tickets, assets, users, or any other DB entity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tables": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of table names you need to answer the question (e.g. ['tickets', 'profiles'])",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "What data you need. Include any filters (e.g. 'Count users grouped by role', or 'List 5 most recent tickets for user_id X')",
                    },
                },
                "required": ["tables", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_faqs",
            "description": "Browse the FAQ knowledge base. Use this first for general 'how do I...' questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Optional keyword to filter FAQs."},
                    "limit": {"type": "integer", "default": 5, "maximum": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Semantic vector search over the knowledge base. Use for fuzzy/conceptual questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The natural-language search query."},
                    "match_count": {"type": "integer", "default": 3, "maximum": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mr_guideline_helper",
            "description": "An agent/tool to help users navigate the system, such as how to go to the helpdesk, how to change a password, or any other system related question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user's question about how to navigate or use the system."},
                },
                "required": ["question"],
            },
        },
    },
]


def execute_tool(name: str, args: dict, ctx: ToolContext) -> Any:
    """Dispatch a tool call. Always returns a JSON-serialisable value."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool '{name}'"}
    try:
        # Add user context to supabase_access args so sub-agent can scope queries
        if name == "supabase_access":
            args["instruction"] = f"{args.get('instruction', '')}. IMPORTANT: Current user_id is '{ctx.user_id}' and role is '{getattr(ctx.user, 'role', 'user')}'. If role is not admin, you MUST scope any queries (like tickets or assets) to only show records where assigned_to or created_by equals this user_id."
        return handler(args or {}, ctx)
    except Exception as e:
        log.exception("Tool %s raised", name)
        return {"error": f"{type(e).__name__}: {e}"}
