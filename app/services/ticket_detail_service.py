"""Names and history shown alongside a ticket in the staff ticket view.

The browser used to read profiles, assets, warehouses and departments straight
from the database with the public anon key. Those reads now come from here,
behind the API's authentication and ticket access rule.
"""
from __future__ import annotations

from typing import Any

from app.deps import is_admin_role


def ticket_details(db: Any, ticket: Any, viewer: Any) -> dict:
    """Creator, assignee, site and status history for a ticket the viewer may see.

    The creator's email address is only included for admins, who use it to
    contact the reporter; other staff see names only.
    """
    from app.models import Asset, Department, Profile, TicketStatusHistory, Warehouse

    history = (
        db.query(TicketStatusHistory)
        .filter(TicketStatusHistory.ticket_id == ticket.id)
        .order_by(TicketStatusHistory.created_at.asc())
        .all()
    )
    people_ids = {i for i in (ticket.created_by, ticket.assigned_to, *(h.changed_by for h in history)) if i}
    people = {
        str(p.id): p
        for p in db.query(Profile.id, Profile.full_name, Profile.email).filter(Profile.id.in_(people_ids)).all()
    } if people_ids else {}

    def name_of(profile_id: Any):
        person = people.get(str(profile_id)) if profile_id else None
        return person.full_name if person else None

    warehouse_name = department_name = None
    warehouse_id = ticket.warehouse_id
    if ticket.asset_id:
        asset = db.query(Asset.warehouse_id, Asset.department_id).filter(Asset.id == ticket.asset_id).first()
        if asset:
            warehouse_id = asset.warehouse_id or warehouse_id
            if asset.department_id:
                department_name = db.query(Department.name).filter(Department.id == asset.department_id).scalar()
    if warehouse_id:
        warehouse_name = db.query(Warehouse.name).filter(Warehouse.id == warehouse_id).scalar()

    creator = people.get(str(ticket.created_by)) if ticket.created_by else None
    return {
        "creator_name": creator.full_name if creator else None,
        "creator_email": creator.email if creator and is_admin_role(viewer) else None,
        "assignee_name": name_of(ticket.assigned_to),
        "warehouse_name": warehouse_name,
        "department_name": department_name,
        "history": [
            {
                "id": h.id,
                "old_status": h.old_status,
                "new_status": h.new_status,
                "changed_by": h.changed_by,
                "changed_by_name": name_of(h.changed_by),
                "note": h.note,
                "created_at": h.created_at,
            }
            for h in history
        ],
    }
