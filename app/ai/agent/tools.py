"""Tool definitions for the PredictiX chatbot agent (v1: read-only).

Each tool is a thin wrapper around an existing service function or DB query.
Tools never call the HTTP layer — they share the same SQLAlchemy session and
the resolved `current_user`, so all role/scope rules are enforced in Python.

Adding a tool:
    1. Write a handler `def _tool_xxx(args, ctx) -> dict | list`.
    2. Add an entry to `TOOL_SCHEMAS` (the JSON schema Groq sees).
    3. Add the handler to `TOOL_HANDLERS`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.db.supabase_client import supabase
from app.models import Asset, Department, Profile, Ticket, Warehouse, Notification, MaintenanceEvent, TicketComment

log = logging.getLogger("predictix.agent.tools")


@dataclass
class ToolContext:
    """Per-request context handed to every tool handler."""
    db: Optional[Session]
    user: Any  # Profile or MockProfile (duck-typed: .id, .role, .department_id, .warehouse_id)

    @property
    def is_admin(self) -> bool:
        return str(getattr(self.user, "role", "")).lower() == "admin"

    @property
    def is_superadmin(self) -> bool:
        return str(getattr(self.user, "role", "")).lower() == "superadmin"

    @property
    def user_id(self) -> str:
        return str(getattr(self.user, "id", ""))

    @property
    def warehouse_id(self) -> str:
        return str(getattr(self.user, "warehouse_id", ""))


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _serialize_ticket(t: Ticket) -> dict:
    return {
        "id": str(t.id),
        "ticket_number": t.ticket_number,
        "title": t.title,
        "description": (t.description or "")[:300],
        "status": t.status,
        "priority": t.priority,
        "predicted_priority": t.predicted_priority,
        "final_priority": t.final_priority,
        "predicted_category": t.predicted_category,
        "final_category": t.final_category,
        "asset_id": str(t.asset_id) if t.asset_id else None,
        "warehouse_id": str(t.warehouse_id) if t.warehouse_id else None,
        "assigned_to": str(t.assigned_to) if t.assigned_to else None,
        "created_by": str(t.created_by) if t.created_by else None,
        "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
    }


def _serialize_asset(a: Asset) -> dict:
    return {
        "id": str(a.id),
        "asset_code": a.asset_code,
        "asset_name": a.asset_name,
        "asset_type": a.asset_type,
        "status": a.status,
        "health_band": a.health_band,
        "criticality_score": float(a.criticality_score) if a.criticality_score is not None else None,
        "make": a.make,
        "model": a.model,
        "manufacture_year": a.manufacture_year,
        "registration_number": a.registration_number,
        "current_mileage": float(a.current_mileage) if a.current_mileage is not None else None,
        "warehouse_id": str(a.warehouse_id) if a.warehouse_id else None,
        "department_id": str(a.department_id) if a.department_id else None,
        "assigned_to": str(a.assigned_to) if a.assigned_to else None,
        "next_service_date": a.next_service_date.isoformat() if a.next_service_date else None,
    }


def _serialize_profile(p: Profile) -> dict:
    return {
        "id": str(p.id),
        "employee_id": p.employee_id,
        "full_name": p.full_name,
        "email": p.email,
        "phone": p.phone,
        "role": p.role,
        "status": p.status,
        "warehouse_id": str(p.warehouse_id) if p.warehouse_id else None,
        "department_id": str(p.department_id) if p.department_id else None,
    }

def _serialize_notification(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "user_id": str(n.user_id),
        "type": n.type,
        "title": n.title,
        "message": n.message,
        "status": n.status,
        "sent_at": n.sent_at.isoformat() if n.sent_at else None,
    }

def _serialize_maintenance_event(m: MaintenanceEvent) -> dict:
    return {
        "id": str(m.id),
        "asset_id": str(m.asset_id),
        "event_type": m.event_type,
        "title": m.title,
        "scheduled_date": m.scheduled_date.isoformat() if m.scheduled_date else None,
        "performed_at": m.performed_at.isoformat() if m.performed_at else None,
        "downtime_hours": float(m.downtime_hours) if m.downtime_hours else None,
        "cost_amount": float(m.cost_amount) if m.cost_amount else None,
    }

def _serialize_ticket_comment(c: TicketComment) -> dict:
    return {
        "id": str(c.id),
        "ticket_id": str(c.ticket_id),
        "user_id": str(c.user_id),
        "comment": c.comment,
        "is_internal": c.is_internal,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }

def _require_db(ctx: ToolContext) -> Session:
    if ctx.db is None:
        raise RuntimeError("Database is not configured for this request.")
    return ctx.db


# ─── Tool handlers ────────────────────────────────────────────────────────────

def _tool_list_tickets(args: dict, ctx: ToolContext) -> dict:
    """List tickets visible to the current user.

    Non-admins only see tickets they created OR are assigned to.
    Admins see everything (with optional filters).
    """
    db = _require_db(ctx)
    q = db.query(Ticket)

    if not (ctx.is_admin or ctx.is_superadmin):
        q = q.filter(
            (Ticket.created_by == ctx.user_id) | (Ticket.assigned_to == ctx.user_id)
        )
    elif ctx.is_admin and not ctx.is_superadmin:
        if ctx.warehouse_id and ctx.warehouse_id != "None":
            q = q.filter(Ticket.warehouse_id == ctx.warehouse_id)

    status = args.get("status")
    priority = args.get("priority")
    asset_id = args.get("asset_id")
    limit = min(int(args.get("limit", 10)), 50)

    if status:
        q = q.filter(Ticket.status == status.lower())
    if priority:
        q = q.filter(Ticket.priority == priority.lower())
    if asset_id:
        q = q.filter(Ticket.asset_id == asset_id)

    total = q.count()
    rows = q.order_by(Ticket.created_at.desc()).limit(limit).all()
    return {
        "count": len(rows),
        "total_count": total,
        "scope": "all" if ctx.is_superadmin else "warehouse" if ctx.is_admin else "own",
        "tickets": [_serialize_ticket(t) for t in rows],
    }


def _tool_get_ticket(args: dict, ctx: ToolContext) -> dict:
    db = _require_db(ctx)
    ticket_id = args.get("ticket_id")
    if not ticket_id:
        return {"error": "ticket_id is required"}

    t = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not t:
        return {"error": "Ticket not found"}

    if not (ctx.is_admin or ctx.is_superadmin) and str(t.created_by) != ctx.user_id and str(t.assigned_to) != ctx.user_id:
        return {"error": "You don't have permission to view this ticket"}
        
    if ctx.is_admin and not ctx.is_superadmin and ctx.warehouse_id and ctx.warehouse_id != "None" and str(t.warehouse_id) != ctx.warehouse_id:
        return {"error": "You don't have permission to view tickets outside your warehouse"}

    return _serialize_ticket(t)


def _tool_list_assets(args: dict, ctx: ToolContext) -> dict:
    db = _require_db(ctx)
    q = db.query(Asset)
    
    if ctx.is_admin and not ctx.is_superadmin:
        if ctx.warehouse_id and ctx.warehouse_id != "None":
            q = q.filter(Asset.warehouse_id == ctx.warehouse_id)

    search = args.get("search")
    status = args.get("status")
    asset_type = args.get("asset_type")
    health_band = args.get("health_band")
    warehouse_id = args.get("warehouse_id")
    limit = min(int(args.get("limit", 10)), 50)

    if search:
        like = f"%{search.strip()}%"
        q = q.filter(
            (Asset.asset_name.ilike(like))
            | (Asset.asset_code.ilike(like))
            | (Asset.make.ilike(like))
            | (Asset.model.ilike(like))
        )
    if status:
        q = q.filter(Asset.status == status)
    if asset_type:
        q = q.filter(Asset.asset_type == asset_type)
    if health_band:
        q = q.filter(Asset.health_band == health_band)
    if warehouse_id:
        q = q.filter(Asset.warehouse_id == warehouse_id)

    total = q.count()
    rows = q.order_by(Asset.asset_name.asc()).limit(limit).all()
    return {
        "count": len(rows),
        "total_count": total,
        "assets": [_serialize_asset(a) for a in rows],
    }


def _tool_get_asset(args: dict, ctx: ToolContext) -> dict:
    db = _require_db(ctx)
    asset_id = args.get("asset_id")
    asset_code = args.get("asset_code")
    if not asset_id and not asset_code:
        return {"error": "Provide either asset_id or asset_code"}

    q = db.query(Asset)
    if asset_id:
        q = q.filter(Asset.id == asset_id)
    elif asset_code:
        q = q.filter(Asset.asset_code == asset_code)

    a = q.first()
    if not a:
        return {"error": "Asset not found"}
        
    if ctx.is_admin and not ctx.is_superadmin and ctx.warehouse_id and ctx.warehouse_id != "None" and str(a.warehouse_id) != ctx.warehouse_id:
        return {"error": "You don't have permission to view assets outside your warehouse"}

    return _serialize_asset(a)


def _tool_list_warehouses(args: dict, ctx: ToolContext) -> dict:
    db = _require_db(ctx)
    q = db.query(Warehouse)
    total = q.count()
    rows = q.order_by(Warehouse.name.asc()).limit(50).all()
    return {
        "count": len(rows),
        "total_count": total,
        "warehouses": [{"id": str(w.id), "name": w.name, "city": getattr(w, "city", None)} for w in rows],
    }


def _tool_list_departments(args: dict, ctx: ToolContext) -> dict:
    db = _require_db(ctx)
    q = db.query(Department)
    if ctx.is_admin and not ctx.is_superadmin:
        if ctx.warehouse_id and ctx.warehouse_id != "None":
            q = q.filter(Department.warehouse_id == ctx.warehouse_id)
            
    total = q.count()
    rows = q.order_by(Department.name.asc()).limit(50).all()
    return {
        "count": len(rows),
        "total_count": total,
        "departments": [{"id": str(d.id), "name": d.name} for d in rows],
    }


def _tool_list_users(args: dict, ctx: ToolContext) -> dict:
    db = _require_db(ctx)
    q = db.query(Profile)
    
    if not ctx.is_superadmin:
        if ctx.is_admin:
            if ctx.warehouse_id and ctx.warehouse_id != "None":
                q = q.filter(Profile.warehouse_id == ctx.warehouse_id)
        else:
            # Regular users can only see people in their own department or warehouse
            user_dept = str(getattr(ctx.user, "department_id", ""))
            user_warehouse = str(getattr(ctx.user, "warehouse_id", ""))
            filters = []
            if user_dept and user_dept != "None":
                filters.append(Profile.department_id == user_dept)
            if user_warehouse and user_warehouse != "None":
                filters.append(Profile.warehouse_id == user_warehouse)
            if filters:
                from sqlalchemy import or_
                q = q.filter(or_(*filters))
            else:
                q = q.filter(Profile.id == ctx.user_id) # Can only see self if no dept/warehouse

    role = args.get("role")
    search = args.get("search")
    
    if role:
        q = q.filter(Profile.role == role.lower())
    if search:
        like = f"%{search.strip()}%"
        q = q.filter((Profile.full_name.ilike(like)) | (Profile.email.ilike(like)))

    total = q.count()
    rows = q.order_by(Profile.full_name.asc()).limit(50).all()
    return {"count": len(rows), "total_count": total, "users": [_serialize_profile(u) for u in rows]}


def _tool_get_user(args: dict, ctx: ToolContext) -> dict:
    db = _require_db(ctx)
    user_id = args.get("user_id")
    if not user_id: return {"error": "user_id is required"}
    u = db.query(Profile).filter(Profile.id == user_id).first()
    if not u: return {"error": "User not found"}
    return _serialize_profile(u)


def _tool_list_notifications(args: dict, ctx: ToolContext) -> dict:
    db = _require_db(ctx)
    # Users can only see their OWN notifications
    q = db.query(Notification).filter(Notification.user_id == ctx.user_id)
    
    status = args.get("status")
    if status:
        q = q.filter(Notification.status == status.lower())
        
    total = q.count()
    rows = q.order_by(Notification.sent_at.desc()).limit(20).all()
    return {"count": len(rows), "total_count": total, "notifications": [_serialize_notification(n) for n in rows]}


def _tool_list_maintenance_events(args: dict, ctx: ToolContext) -> dict:
    db = _require_db(ctx)
    q = db.query(MaintenanceEvent)
    
    if ctx.is_admin and not ctx.is_superadmin:
        if ctx.warehouse_id and ctx.warehouse_id != "None":
            q = q.join(Asset, MaintenanceEvent.asset_id == Asset.id).filter(Asset.warehouse_id == ctx.warehouse_id)
            
    asset_id = args.get("asset_id")
    if asset_id:
        q = q.filter(MaintenanceEvent.asset_id == asset_id)
        
    total = q.count()
    rows = q.order_by(MaintenanceEvent.scheduled_date.desc()).limit(20).all()
    return {"count": len(rows), "total_count": total, "events": [_serialize_maintenance_event(m) for m in rows]}


def _tool_list_ticket_comments(args: dict, ctx: ToolContext) -> dict:
    db = _require_db(ctx)
    ticket_id = args.get("ticket_id")
    if not ticket_id: return {"error": "ticket_id is required"}
    
    q = db.query(TicketComment).filter(TicketComment.ticket_id == ticket_id)
    
    # Restrict visibility based on ticket's warehouse
    if ctx.is_admin and not ctx.is_superadmin:
        if ctx.warehouse_id and ctx.warehouse_id != "None":
            q = q.join(Ticket, TicketComment.ticket_id == Ticket.id).filter(Ticket.warehouse_id == ctx.warehouse_id)
            
    if not ctx.is_admin and not ctx.is_superadmin:
        # Regular users cannot see internal comments
        q = q.filter(TicketComment.is_internal == False)
        
    total = q.count()
    rows = q.order_by(TicketComment.created_at.asc()).limit(50).all()
    return {"count": len(rows), "total_count": total, "comments": [_serialize_ticket_comment(c) for c in rows]}


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


def _tool_categorize_ticket(args: dict, ctx: ToolContext) -> dict:
    from app.ai.services.ticket_categorization_service import categorize_ticket_text

    title = args.get("title", "")
    description = args.get("description", "")
    try:
        return categorize_ticket_text(title=title, description=description)
    except Exception as e:
        return {"error": str(e)}


def _tool_classify_priority(args: dict, ctx: ToolContext) -> dict:
    from app.ai.services.ticket_priority_service import classify_ticket_priority

    text = args.get("text", "")
    if not text:
        return {"error": "text is required"}
    try:
        priority = classify_ticket_priority(text)
        return {"priority": priority}
    except Exception as e:
        return {"error": str(e)}


def _tool_predict_failure(args: dict, ctx: ToolContext) -> dict:
    """Run the PdM classifier on a feature dict.

    The model expects numeric features matching the trained schema; pass them
    through as-is. The agent may also call list_assets first to look them up.
    """
    from app import main as app_main

    if app_main.clf_model is None:
        return {"error": "PdM classifier model is not loaded"}

    features = args.get("features") or {}
    if not features:
        return {"error": "features dict is required"}

    try:
        import pandas as pd

        feature_names = app_main.clf_features or list(features.keys())
        row = {name: features.get(name, 0) for name in feature_names}
        df = pd.DataFrame([row])
        pred = app_main.clf_model.predict(df)[0]
        proba = None
        if hasattr(app_main.clf_model, "predict_proba"):
            probs = app_main.clf_model.predict_proba(df)[0]
            proba = {str(c): float(p) for c, p in zip(app_main.clf_model.classes_, probs)}
        return {"prediction": str(pred), "probabilities": proba}
    except Exception as e:
        log.exception("predict_failure tool failed")
        return {"error": str(e)}


def _tool_predict_days_to_maintenance(args: dict, ctx: ToolContext) -> dict:
    from app import main as app_main

    if app_main.reg_model is None:
        return {"error": "PdM regressor model is not loaded"}

    features = args.get("features") or {}
    if not features:
        return {"error": "features dict is required"}

    try:
        import pandas as pd

        feature_names = app_main.reg_features or list(features.keys())
        row = {name: features.get(name, 0) for name in feature_names}
        df = pd.DataFrame([row])
        pred = float(app_main.reg_model.predict(df)[0])
        return {"days_until_maintenance": round(pred, 1)}
    except Exception as e:
        log.exception("predict_days_to_maintenance tool failed")
        return {"error": str(e)}


def _tool_whoami(args: dict, ctx: ToolContext) -> dict:
    """Return basic info about the current user — useful for the agent's reasoning."""
    return {
        "id": ctx.user_id,
        "email": getattr(ctx.user, "email", None),
        "role": getattr(ctx.user, "role", "user"),
        "full_name": getattr(ctx.user, "full_name", None),
        "department_id": str(ctx.user.department_id) if getattr(ctx.user, "department_id", None) else None,
        "warehouse_id": str(ctx.user.warehouse_id) if getattr(ctx.user, "warehouse_id", None) else None,
    }


# ─── Tool registry ────────────────────────────────────────────────────────────

TOOL_HANDLERS: dict[str, Callable[[dict, ToolContext], Any]] = {
    "whoami": _tool_whoami,
    "list_users": _tool_list_users,
    "get_user": _tool_get_user,
    "list_notifications": _tool_list_notifications,
    "list_maintenance_events": _tool_list_maintenance_events,
    "list_ticket_comments": _tool_list_ticket_comments,
    "list_tickets": _tool_list_tickets,
    "get_ticket": _tool_get_ticket,
    "list_assets": _tool_list_assets,
    "get_asset": _tool_get_asset,
    "list_warehouses": _tool_list_warehouses,
    "list_departments": _tool_list_departments,
    "list_faqs": _tool_list_faqs,
    "search_knowledge": _tool_search_knowledge,
    "categorize_ticket": _tool_categorize_ticket,
    "classify_priority": _tool_classify_priority,
    "predict_failure": _tool_predict_failure,
    "predict_days_to_maintenance": _tool_predict_days_to_maintenance,
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
            "name": "list_users",
            "description": "List users in the system. Use this to count users, find admins, or search by name. Regular users only see their department/warehouse.",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "description": "Filter by role (e.g. admin, user, superadmin)"},
                    "search": {"type": "string", "description": "Search by name or email"}
                },
                "required": []
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user",
            "description": "Get detailed information about a specific user by their ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "The UUID of the user"}
                },
                "required": ["user_id"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_notifications",
            "description": "List the current user's notifications. Use this to check for alerts or updates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by status (e.g. unread, read)"}
                },
                "required": []
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_maintenance_events",
            "description": "List maintenance events for assets. Use this to check scheduled or past maintenance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string", "description": "Filter by asset UUID"}
                },
                "required": []
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_ticket_comments",
            "description": "List the conversation and comments on a specific ticket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string", "description": "The UUID of the ticket"}
                },
                "required": ["ticket_id"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tickets",
            "description": "List support tickets visible to the user. Non-admins only see tickets they created or are assigned to; admins see all.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "in_progress", "pending", "resolved", "closed", "cancelled"], "description": "Filter by status."},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "Filter by priority."},
                    "asset_id": {"type": "string", "description": "Filter by asset UUID."},
                    "limit": {"type": "integer", "default": 10, "maximum": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticket",
            "description": "Fetch a single ticket by its ID.",
            "parameters": {
                "type": "object",
                "properties": {"ticket_id": {"type": "string", "description": "Ticket UUID."}},
                "required": ["ticket_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_assets",
            "description": "List assets (vehicles, equipment) with optional filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Substring match on name, code, make, or model."},
                    "status": {"type": "string", "description": "Filter by status (e.g. 'active', 'inactive')."},
                    "asset_type": {"type": "string", "description": "Filter by asset type (e.g. 'vehicle')."},
                    "health_band": {"type": "string", "description": "Filter by health band (e.g. 'excellent', 'critical')."},
                    "warehouse_id": {"type": "string", "description": "Filter by warehouse UUID."},
                    "limit": {"type": "integer", "default": 10, "maximum": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_asset",
            "description": "Fetch a single asset by its ID or asset code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string", "description": "Asset UUID."},
                    "asset_code": {"type": "string", "description": "Human-readable asset code, e.g. 'FL-22'."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_warehouses",
            "description": "List all warehouses in the system.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_departments",
            "description": "List all departments in the system.",
            "parameters": {"type": "object", "properties": {}, "required": []},
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
            "name": "categorize_ticket",
            "description": "Run the AI ticket-categorization model on a ticket's title + description. Returns predicted category (electrical/mechanical/software) with confidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_priority",
            "description": "Run the AI ticket-priority XGBoost model on a ticket text. Returns Low/Medium/High.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "The ticket text (title + description concatenated)."}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_failure",
            "description": "Run the predictive-maintenance classifier on a feature dict. Returns failure class + class probabilities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "features": {
                        "type": "object",
                        "description": "Numeric feature dict matching the trained schema (e.g. {temperature, vibration, pressure, ...}).",
                    },
                },
                "required": ["features"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_days_to_maintenance",
            "description": "Run the predictive-maintenance regressor. Returns estimated days until next maintenance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "features": {
                        "type": "object",
                        "description": "Numeric feature dict matching the trained regressor schema.",
                    },
                },
                "required": ["features"],
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
        return handler(args or {}, ctx)
    except Exception as e:
        log.exception("Tool %s raised", name)
        return {"error": f"{type(e).__name__}: {e}"}
