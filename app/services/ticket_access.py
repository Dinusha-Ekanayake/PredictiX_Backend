"""Who may see a ticket through the staff ticket routes.

One rule for every staff route that reads or attaches to a ticket (comments,
status history, attachments, details), so they cannot drift apart:

- Admins and super admins see every ticket in their active warehouse, and
  only those.
- Everyone else sees any ticket in their own warehouse, plus tickets they
  created or are assigned to elsewhere.

The /user/tickets routes apply their own, stricter rule
(app.services.user_ticket_service.user_can_view_ticket).
"""
from __future__ import annotations

from typing import Any

from app.deps import is_admin_role, scoped_warehouse_id


def can_view_ticket(ticket: Any, user: Any) -> bool:
    if is_admin_role(user):
        warehouse_id = scoped_warehouse_id(user)
        return bool(warehouse_id) and str(ticket.warehouse_id) == warehouse_id
    user_id = str(getattr(user, "id", ""))
    user_warehouse = getattr(user, "warehouse_id", None)
    if user_warehouse is not None and str(ticket.warehouse_id) == str(user_warehouse):
        return True
    return str(ticket.created_by) == user_id or str(ticket.assigned_to) == user_id
