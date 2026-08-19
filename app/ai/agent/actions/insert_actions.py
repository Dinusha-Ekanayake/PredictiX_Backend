import json
import logging
from typing import Optional
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
    """Best-effort normalization of the LLM's free-text priority guess.
    Falls back to 'medium' for anything unrecognized rather than raising, this is chat-agent output, not a strict API contract, so a silent
    fallback beats surfacing a generic error for a minor LLM quirk."""
    v = (raw or "medium").strip().lower()
    if v in {"critical", "urgent", "severe"}:
        v = "high"
    return v if v in _VALID_PRIORITIES else "medium"


def _normalize_status(raw: Optional[str]) -> Optional[str]:
    """Same best-effort approach as _normalize_priority. Returns None
    (meaning "don't change it") for anything unrecognized instead of
    letting an invalid enum value hit the DB and fail the whole commit."""
    v = (raw or "").strip().lower().replace(" ", "_")
    return v if v in _VALID_STATUSES else None

ACTION_PROMPT = """
You are the Action Router for PredictiX Sidekick.
The user wants to perform an action (create a ticket/asset/user, or update a ticket).
You MUST NOT perform delete operations. If the user asks to delete, return {"action": "unauthorized"}.

Determine the action type and extract the fields from the user's request.
Return exactly ONE JSON object (and nothing else) matching one of these formats:

For Ticket Creation:
{
  "action": "create_ticket",
  "title": "<short title>",
  "description": "<detailed description>",
  "priority": "<low|medium|high|null>"
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

def handle_action(question: str, ctx: ToolContext) -> dict:
    """Handles data insertion requests strictly."""
    
    # Use LLM to parse the intent into structured JSON
    try:
        raw_json, _ = call_groq(
            messages=[
                {"role": "system", "content": ACTION_PROMPT},
                {"role": "user", "content": question}
            ],
            max_tokens=200,
            temperature=0.1
        )
        
        # Clean up any markdown blocks around JSON
        raw_json_clean = str(raw_json).strip()
        if raw_json_clean.startswith("```json"):
            raw_json_clean = raw_json_clean[7:-3].strip()
            
        data = json.loads(raw_json_clean)
        action = data.get("action")
        
    except Exception as e:
        log.error("Failed to parse action JSON: %s", e)
        return {"answer": "⚠️ I couldn't understand the action details. Please try again.", "action_buttons": []}
        
    if action == "unauthorized":
        return {"answer": "🔒 I am only allowed to create new records. I cannot update or delete existing data.", "action_buttons": []}

    try:
        # 1. Create Ticket
        if action == "create_ticket":
            # Anyone can create a ticket
            new_ticket = Ticket(
                id=uuid.uuid4(),
                ticket_number=generate_ticket_number(ctx.db),
                title=data.get("title") or "New Ticket from Chat",
                description=data.get("description") or "Created via Sidekick",
                priority=_normalize_priority(data.get("priority")),
                created_by=uuid.UUID(ctx.user_id),
                status="open",
                warehouse_id=uuid.UUID(ctx.warehouse_id) if ctx.warehouse_id else None
            )
            ctx.db.add(new_ticket)
            ctx.db.commit()
            
            base_path = "/admin/tickets" if ctx.is_admin else "/user/tickets"
            return {
                "answer": f"✅ Successfully created a new ticket: **{new_ticket.title}**.",
                "action_buttons": [{"label": "View Ticket", "path": f"{base_path}?ticket_id={new_ticket.id}"}]
            }
            
        # 2. Create Asset
        elif action == "create_asset":
            # RBAC: Only Admins can create assets
            if not ctx.is_admin:
                return {"answer": "🔒 You do not have permission to create assets. Only admins can perform this action.", "action_buttons": []}
                
            new_asset = Asset(
                id=uuid.uuid4(),
                asset_name=data.get("asset_name") or "New Asset",
                asset_code=data.get("asset_code") or f"AST-{uuid.uuid4().hex[:6].upper()}",
                asset_type=data.get("asset_type") or "vehicle",
                status="active",
                warehouse_id=uuid.UUID(ctx.warehouse_id) if ctx.warehouse_id else None
            )
            ctx.db.add(new_asset)
            ctx.db.commit()
            
            return {
                "answer": f"✅ Successfully created a new asset: **{new_asset.asset_name}** ({new_asset.asset_code}).",
                "action_buttons": [{"label": "View Asset", "path": f"/admin/assets?asset_id={new_asset.id}"}]
            }
            
        # 3. Create User
        elif action == "create_user":
            # RBAC: Only Admins can create users
            if not ctx.is_admin:
                return {"answer": "🔒 You do not have permission to create users. Only admins can perform this action.", "action_buttons": []}
                
            email = data.get("email")
            if not email:
                return {"answer": "⚠️ I need an email address to create a new user.", "action_buttons": []}
                
            new_profile = Profile(
                id=uuid.uuid4(),
                email=email,
                full_name=data.get("full_name") or "New User",
                role=data.get("role") or "user",
                warehouse_id=uuid.UUID(ctx.warehouse_id) if ctx.warehouse_id else None
            )
            ctx.db.add(new_profile)
            ctx.db.commit()
            
            return {
                "answer": f"✅ Successfully created a new user: **{new_profile.full_name}** ({email}).",
                "action_buttons": [{"label": "View User", "path": f"/users/{new_profile.id}"}]
            }
            
        # 4. Update Ticket
        elif action == "update_ticket":
            # RBAC: Only Admins can update tickets
            if not ctx.is_admin:
                return {"answer": "🔒 You do not have permission to update tickets. Only admins can perform this action.", "action_buttons": []}
                
            ticket_id_str = str(data.get("ticket_id"))
            
            # Find the ticket by ticket_number or ID
            ticket = None
            if ticket_id_str.isdigit() or ticket_id_str.startswith("#"):
                num = ticket_id_str.replace("#", "")
                if num.isdigit():
                    ticket = ctx.db.query(Ticket).filter(Ticket.ticket_number == int(num)).first()
            else:
                try:
                    ticket_uuid = uuid.UUID(ticket_id_str)
                    ticket = ctx.db.query(Ticket).filter(Ticket.id == ticket_uuid).first()
                except ValueError:
                    pass
                    
            if not ticket:
                return {"answer": f"⚠️ I couldn't find a ticket matching '{ticket_id_str}'. Please check the ticket number.", "action_buttons": []}
                
            updated_fields = []
            new_status = _normalize_status(data.get("status"))
            if new_status and new_status != ticket.status:
                ticket.status = new_status
                updated_fields.append(f"status to '{ticket.status}'")
            if data.get("priority"):
                new_priority = _normalize_priority(data.get("priority"))
                if new_priority != ticket.priority:
                    ticket.priority = new_priority
                    updated_fields.append(f"priority to '{ticket.priority}'")
                
            if not updated_fields:
                return {"answer": f"The ticket is already up-to-date. No changes were made.", "action_buttons": [{"label": "View Ticket", "path": f"/tickets/{ticket.id}"}]}
                
            ctx.db.commit()
            changes = " and ".join(updated_fields)
            return {
                "answer": f"✅ Successfully updated ticket #{ticket.ticket_number}: changed {changes}.",
                "action_buttons": [{"label": "View Ticket", "path": f"/tickets/{ticket.id}"}]
            }
            
        else:
            return {"answer": "⚠️ Unknown action type requested.", "action_buttons": []}
            
    except Exception as e:
        log.error("Database error during action execution: %s", e)
        ctx.db.rollback()
        return {"answer": "⚠️ An error occurred while trying to save the data.", "action_buttons": []}
