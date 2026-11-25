"""Row scoping for the chatbot's ORM lookups.

The same visibility rules as the REST endpoints (see app/deps.py): admins and
super admins see their active warehouse, an admin with no warehouse sees
nothing (the REST endpoints refuse them), and users see their own warehouse plus records assigned to or raised
by them.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import false, or_

from app.models import Asset, Profile, Ticket


def _caller_uuid(ctx: Any) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(ctx.user_id))
    except (ValueError, TypeError, AttributeError):
        return None


def _admin_warehouse(ctx: Any) -> Optional[str]:
    from app.deps import scoped_warehouse_id

    return scoped_warehouse_id(ctx.user)


def _user_conditions(ctx: Any, model, owner_columns: tuple) -> list:
    conditions = []
    uid = _caller_uuid(ctx)
    if uid is not None:
        conditions.extend(getattr(model, col) == uid for col in owner_columns)
    user_wh = getattr(ctx.user, "warehouse_id", None)
    if user_wh is not None:
        conditions.append(model.warehouse_id == user_wh)
    return conditions


def scope_asset_query(query, ctx: Any):
    if ctx.is_admin:
        wh_id = _admin_warehouse(ctx)
        return query.filter(Asset.warehouse_id == wh_id) if wh_id else query.filter(false())
    conditions = _user_conditions(ctx, Asset, ("assigned_to",))
    return query.filter(or_(*conditions)) if conditions else query.filter(false())


def scope_ticket_query(query, ctx: Any):
    if ctx.is_admin:
        wh_id = _admin_warehouse(ctx)
        return query.filter(Ticket.warehouse_id == wh_id) if wh_id else query.filter(false())
    conditions = _user_conditions(ctx, Ticket, ("created_by", "assigned_to"))
    return query.filter(or_(*conditions)) if conditions else query.filter(false())


def scope_profile_query(query, ctx: Any):
    if ctx.is_admin:
        wh_id = _admin_warehouse(ctx)
        return query.filter(Profile.warehouse_id == wh_id) if wh_id else query.filter(false())
    user_wh = getattr(ctx.user, "warehouse_id", None)
    return query.filter(Profile.warehouse_id == user_wh) if user_wh is not None else query.filter(false())
