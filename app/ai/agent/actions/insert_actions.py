import json
import logging
import re
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import uuid

from app.ai.agent.tools import ToolContext
from app.ai.services.llm_service import call_groq
from app.models import Ticket, Asset, Profile
from app.services.user_ticket_service import generate_ticket_number

log = logging.getLogger("predictix.actions")

_VALID_PRIORITIES = {"low", "medium", "high"}
_VALID_STATUSES = {"open", "in_progress", "pending", "resolved", "closed", "cancelled"}


def _normalize_priority(raw: Optional[str]) -> str:
    """Best-effort normalization of the LLM's free-text priority guess."""
    v = (raw or "medium").strip().lower()
    if v in {"critical", "urgent", "severe"}:
        v = "high"
    return v if v in _VALID_PRIORITIES else "medium"


def _normalize_status(raw: Optional[str]) -> Optional[str]:
    """Same best-effort approach as _normalize_priority."""
    v = (raw or "").strip().lower().replace(" ", "_")
    return v if v in _VALID_STATUSES else None


def _extract_json_data(text: str) -> dict:
    """Safely extract JSON object from LLM response even with markdown fences or extra text."""
    s = str(text or "").strip()
    
    # 1. Clean markdown code blocks
    s_cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s_cleaned = re.sub(r"\s*```$", "", s_cleaned).strip()
    
    try:
        return json.loads(s_cleaned)
    except Exception:
        pass

    # 2. Extract first {...} structure with regex
    match = re.search(r"\{[\s\S]*\}", s)
    if match:
        json_str = match.group(0)
        try:
            return json.loads(json_str)
        except Exception:
            # Try cleaning trailing commas
            cleaned_commas = re.sub(r",\s*([\]}])", r"\1", json_str)
            return json.loads(cleaned_commas)

    raise ValueError(f"No valid JSON found in response: {s[:100]}")


ACTION_PROMPT = """
You are the Action Router for PredictiX Sidekick.
The user wants to perform an action (create a ticket/asset/user, or update a ticket).
You MUST NOT perform delete operations. If the user asks to delete, return {"action": "unauthorized"}.

Determine the action type and extract the fields from the user's request.
Return ONLY valid JSON (no extra text, no explanation) matching one of these formats:

For Ticket Creation:
{
  "action": "create_ticket",
  "title": "<short descriptive title>",
  "description": "<detailed description of the issue>",
  "priority": "<low|medium|high>",
  "asset_name": "<asset name or code if mentioned, e.g. 'Forklift FL-04', 'FL-04', or null>"
}

For Asset Creation:
{
  "action": "create_asset",
  "asset_name": "<name>",
  "asset_code": "<code or null>",
  "asset_type": "<vehicle|hvac|machinery|null>"
}

For User Creation:
{
  "action": "create_user",
  "email": "<email>",
  "full_name": "<full name>",
  "role": "<admin|user|null>"
}

For Ticket Update (Status/Priority):
{
  "action": "update_ticket",
  "ticket_id": "<number or ID>",
  "status": "<open|in_progress|resolved|closed|null>",
  "priority": "<low|medium|high|null>"
}

If you cannot understand the action or it's a delete operation, return:
{
  "action": "unauthorized"
}
"""


def _parse_action_rule_based(question: str) -> dict:
    """Deterministic regex-based fallback for action parsing when LLM is unavailable."""
    q = question.strip()
    q_lower = q.lower()

    # 1. Create Ticket
    if any(k in q_lower for k in ["ticket", "fault", "issue", "breakdown", "complaint", "incident"]):
        priority = "medium"
        if "high priority" in q_lower or "urgent" in q_lower or "critical" in q_lower:
            priority = "high"
        elif "low priority" in q_lower:
            priority = "low"

        # Extract title
        title = "New Maintenance Ticket"
        title_match = re.search(r"titled\s+['\"]?([^'\"]+?)['\"]?(?:\s+with\s+description|\s+for|\s*$)", q, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
        else:
            t_match2 = re.search(r"ticket\s+(?:for\s+[^'\"]+?\s+)?titled\s+['\"]?([^'\"]+?)['\"]?", q, re.IGNORECASE)
            if t_match2:
                title = t_match2.group(1).strip()

        # Extract description
        desc = "Created via Sidekick Chatbot"
        desc_match = re.search(r"description\s+['\"]?([^'\"]+?)['\"]?$", q, re.IGNORECASE)
        if desc_match:
            desc = desc_match.group(1).strip()
        elif "with description" in q_lower:
            desc = q.split("with description", 1)[1].strip(" '\"")

        # Extract asset
        asset_name = None
        asset_match = re.search(r"for\s+([A-Za-z0-9\-\s]+?)\s+(?:titled|with|priority)", q, re.IGNORECASE)
        if asset_match:
            asset_name = asset_match.group(1).strip()

        return {
            "action": "create_ticket",
            "title": title,
            "description": desc,
            "priority": priority,
            "asset_name": asset_name
        }

    # 2. Create Asset
    if "asset" in q_lower and ("create" in q_lower or "add" in q_lower or "insert" in q_lower):
        name_match = re.search(r"(?:asset|name)\s+['\"]?([^'\"]+?)['\"]?(?:\s+type|\s+code|$)", q, re.IGNORECASE)
        name = name_match.group(1).strip() if name_match else "New Asset"
        return {
            "action": "create_asset",
            "asset_name": name,
            "asset_code": None,
            "asset_type": "vehicle"
        }

    # 3. Create User
    if "user" in q_lower and ("create" in q_lower or "add" in q_lower or "insert" in q_lower):
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", q)
        email = email_match.group(0) if email_match else None
        return {
            "action": "create_user",
            "email": email,
            "full_name": "New User",
            "role": "user"
        }

    return {"action": "unauthorized"}


def handle_action(question: str, ctx: ToolContext) -> dict:
    """Handles data insertion requests strictly."""
    
    # 1. Use LLM to parse the intent into structured JSON with regex fallback
    try:
        raw_json, _ = call_groq(
            messages=[
                {"role": "system", "content": ACTION_PROMPT},
                {"role": "user", "content": question}
            ],
            max_tokens=300,
            temperature=0.0
        )
        data = _extract_json_data(raw_json)
        action = data.get("action")
    except Exception as e:
        log.warning("LLM action parsing failed, falling back to rule-based parser: %s", e)
        data = _parse_action_rule_based(question)
        action = data.get("action")
        
    if not data or action == "unauthorized":
        return {"answer": "🔒 I am only allowed to create or update maintenance records. I cannot delete existing data.", "action_buttons": []}

    # Ensure valid database session
    db = ctx.db
    should_close_db = False
    if db is None or not getattr(db, "is_active", True):
        from app.db.session import SessionLocal
        db = SessionLocal()
        should_close_db = True

    try:
        # 1. Create Ticket
        if action == "create_ticket":
            # Search for referenced asset if provided
            asset = None
            asset_ref = data.get("asset_name") or data.get("asset_code")
            if asset_ref:
                asset_clean = str(asset_ref).strip()
                asset = (
                    db.query(Asset)
                    .filter(
                        or_(
                            Asset.asset_code.ilike(f"%{asset_clean}%"),
                            Asset.asset_name.ilike(f"%{asset_clean}%"),
                            Asset.registration_number.ilike(f"%{asset_clean}%"),
                        )
                    )
                    .first()
                )

            # Resolve creator UUID
            created_by_uuid = None
            if ctx.user_id:
                try:
                    created_by_uuid = uuid.UUID(str(ctx.user_id))
                except Exception:
                    pass
            if not created_by_uuid:
                first_prof = db.query(Profile).filter(Profile.status == "active").first()
                if first_prof:
                    created_by_uuid = first_prof.id

            # Resolve warehouse ID
            wh_id = None
            if asset and asset.warehouse_id:
                wh_id = asset.warehouse_id
            elif ctx.warehouse_id:
                try:
                    wh_id = uuid.UUID(str(ctx.warehouse_id))
                except Exception:
                    pass

            ticket_num = generate_ticket_number(db)
            priority_val = _normalize_priority(data.get("priority"))
            title_val = data.get("title") or "New Maintenance Ticket"
            desc_val = data.get("description") or "Created via Sidekick Chatbot"

            new_ticket = Ticket(
                id=uuid.uuid4(),
                ticket_number=ticket_num,
                title=title_val,
                description=desc_val,
                priority=priority_val,
                created_by=created_by_uuid,
                asset_id=asset.id if asset else None,
                warehouse_id=wh_id,
                status="open",
            )
            db.add(new_ticket)
            db.commit()
            db.refresh(new_ticket)

            # Trigger email notification asynchronously
            try:
                import threading
                from app.services.notification_service import NotificationService
                t_id_str = str(new_ticket.id)
                threading.Thread(
                    target=lambda: NotificationService.notify_on_new_ticket(None, t_id_str),
                    daemon=True
                ).start()
            except Exception as notify_err:
                log.warning("Notification dispatch failed on chatbot ticket create: %s", notify_err)
            
            base_path = "/admin/tickets" if ctx.is_admin else "/user/tickets"
            asset_info = f" for **{asset.asset_name}** (`{asset.asset_code}`)" if asset else ""
            
            return {
                "answer": (
                    f"✅ **Ticket Created Successfully!**\n\n"
                    f"• **Ticket Number:** `{new_ticket.ticket_number}`\n"
                    f"• **Title:** {new_ticket.title}\n"
                    f"• **Priority:** `{new_ticket.priority.upper()}`\n"
                    f"• **Status:** `OPEN`"
                    f"{asset_info}\n\n"
                    f"Our maintenance team has been notified via email."
                ),
                "action_buttons": [{"label": "View Ticket", "path": f"{base_path}?ticket_id={new_ticket.id}"}]
            }
            
        # 2. Create Asset
        elif action == "create_asset":
            if not ctx.is_admin:
                return {"answer": "🔒 You do not have permission to create assets. Only admins can perform this action.", "action_buttons": []}
                
            wh_id = None
            if ctx.warehouse_id:
                try:
                    wh_id = uuid.UUID(str(ctx.warehouse_id))
                except Exception:
                    pass

            new_asset = Asset(
                id=uuid.uuid4(),
                asset_name=data.get("asset_name") or "New Asset",
                asset_code=data.get("asset_code") or f"AST-{uuid.uuid4().hex[:6].upper()}",
                asset_type=data.get("asset_type") or "vehicle",
                status="active",
                warehouse_id=wh_id
            )
            db.add(new_asset)
            db.commit()
            db.refresh(new_asset)
            
            return {
                "answer": f"✅ Successfully created new asset: **{new_asset.asset_name}** (`{new_asset.asset_code}`).",
                "action_buttons": [{"label": "View Asset", "path": f"/admin/assets?asset_id={new_asset.id}"}]
            }
            
        # 3. Create User
        elif action == "create_user":
            if not ctx.is_admin:
                return {"answer": "🔒 You do not have permission to create users. Only admins can perform this action.", "action_buttons": []}
                
            email = data.get("email")
            if not email:
                return {"answer": "⚠️ I need an email address to create a new user.", "action_buttons": []}
                
            wh_id = None
            if ctx.warehouse_id:
                try:
                    wh_id = uuid.UUID(str(ctx.warehouse_id))
                except Exception:
                    pass

            new_profile = Profile(
                id=uuid.uuid4(),
                email=email,
                full_name=data.get("full_name") or "New User",
                role=data.get("role") or "user",
                warehouse_id=wh_id
            )
            db.add(new_profile)
            db.commit()
            db.refresh(new_profile)
            
            return {
                "answer": f"✅ Successfully created new user: **{new_profile.full_name}** (`{email}`).",
                "action_buttons": [{"label": "View User", "path": f"/users/{new_profile.id}"}]
            }
            
        # 4. Update Ticket
        elif action == "update_ticket":
            if not ctx.is_admin:
                return {"answer": "🔒 You do not have permission to update tickets. Only admins can perform this action.", "action_buttons": []}
                
            ticket_id_str = str(data.get("ticket_id") or "").strip()
            
            ticket = None
            if ticket_id_str.isdigit() or ticket_id_str.startswith("#"):
                num = ticket_id_str.replace("#", "")
                ticket = db.query(Ticket).filter(Ticket.ticket_number.ilike(f"%{num}%")).first()
            elif ticket_id_str.upper().startswith("TKT-") or ticket_id_str.upper().startswith("T-"):
                ticket = db.query(Ticket).filter(Ticket.ticket_number.ilike(f"%{ticket_id_str}%")).first()
            else:
                try:
                    ticket_uuid = uuid.UUID(ticket_id_str)
                    ticket = db.query(Ticket).filter(Ticket.id == ticket_uuid).first()
                except ValueError:
                    ticket = db.query(Ticket).filter(Ticket.ticket_number.ilike(f"%{ticket_id_str}%")).first()
                    
            if not ticket:
                return {"answer": f"⚠️ I couldn't find a ticket matching '{ticket_id_str}'. Please verify the ticket number.", "action_buttons": []}
                
            updated_fields = []
            new_status = _normalize_status(data.get("status"))
            if new_status and new_status != ticket.status:
                ticket.status = new_status
                updated_fields.append(f"status to **{ticket.status.upper()}**")
            if data.get("priority"):
                new_priority = _normalize_priority(data.get("priority"))
                if new_priority != ticket.priority:
                    ticket.priority = new_priority
                    updated_fields.append(f"priority to **{ticket.priority.upper()}**")
                
            if not updated_fields:
                return {"answer": f"Ticket **{ticket.ticket_number}** is already up-to-date.", "action_buttons": [{"label": "View Ticket", "path": f"/admin/tickets?ticket_id={ticket.id}"}]}
                
            db.commit()
            changes = " and ".join(updated_fields)
            return {
                "answer": f"✅ Successfully updated ticket **{ticket.ticket_number}**: changed {changes}.",
                "action_buttons": [{"label": "View Ticket", "path": f"/admin/tickets?ticket_id={ticket.id}"}]
            }
            
        else:
            return {"answer": "⚠️ Unknown action type requested.", "action_buttons": []}
            
    except Exception as e:
        log.error("Database error during action execution: %s", e)
        if db:
            db.rollback()
        return {"answer": "⚠️ An error occurred while trying to save the data.", "action_buttons": []}
    finally:
        if should_close_db and db:
            db.close()

