"""Service-layer happy-path tests for the user-ticket section."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import user_ticket_service as svc


# ---------------------------------------------------------------------------
# Ticket number generation
# ---------------------------------------------------------------------------


def test_generate_ticket_number_uses_year_and_count():
    db = MagicMock()
    db.query.return_value.filter.return_value.count.return_value = 4

    number = svc.generate_ticket_number(
        db, now=datetime(2026, 5, 30, tzinfo=timezone.utc)
    )

    assert number == "TKT-2026-0005"


def test_generate_ticket_number_pads_to_four_digits():
    db = MagicMock()
    db.query.return_value.filter.return_value.count.return_value = 0

    number = svc.generate_ticket_number(
        db, now=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert number == "TKT-2026-0001"


# ---------------------------------------------------------------------------
# AI soft-fail wrappers
# ---------------------------------------------------------------------------


def test_predict_priority_safely_returns_dict_on_success():
    fake = {"predicted_label": "high", "confidence": 0.91, "scores": []}
    with patch(
        "app.ai.services.ticket_priority_service.predict_ticket_priority",
        return_value=fake,
    ):
        result = svc.predict_priority_safely("title", "description")
    assert result == fake


def test_predict_priority_safely_returns_none_on_failure():
    with patch(
        "app.ai.services.ticket_priority_service.predict_ticket_priority",
        side_effect=RuntimeError("HF unavailable"),
    ):
        assert svc.predict_priority_safely("t", "d") is None


def test_predict_category_safely_returns_none_on_failure():
    with patch(
        "app.ai.services.ticket_categorization_service.categorize_ticket_text",
        side_effect=ValueError("bad input"),
    ):
        assert svc.predict_category_safely("t", "d") is None


def test_generate_summary_safely_passes_through_on_success():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with patch(
        "app.ai.services.ticket_summary_service.generate_ticket_summary",
        return_value="Short ticket summary.",
    ), patch(
        "app.ai.services.ticket_summary_service.build_ticket_summary_input",
        return_value="formatted",
    ):
        summary = svc.generate_summary_safely(
            db,
            title="t",
            description="d",
            asset_id=None,
            category="hydraulics",
            priority="high",
        )

    assert summary == "Short ticket summary."


def test_generate_summary_safely_returns_none_on_failure():
    db = MagicMock()
    with patch(
        "app.ai.services.ticket_summary_service.generate_ticket_summary",
        side_effect=RuntimeError("model down"),
    ):
        assert (
            svc.generate_summary_safely(
                db,
                title="t",
                description="d",
                asset_id=None,
                category=None,
                priority=None,
            )
            is None
        )


# ---------------------------------------------------------------------------
# Update field whitelist
# ---------------------------------------------------------------------------


def test_update_user_ticket_only_applies_whitelisted_fields(make_ticket):
    ticket = make_ticket(title="old", description="old desc", priority="low")
    db = MagicMock()

    svc.update_user_ticket(
        db,
        ticket,
        {
            "title": "new",
            "description": "new desc",
            "priority": "high",
            # disallowed fields must be ignored:
            "status": "closed",
            "assigned_to": uuid.uuid4(),
            "final_priority": "critical",
        },
    )

    assert ticket.title == "new"
    assert ticket.description == "new desc"
    assert ticket.priority == "high"
    assert ticket.status == "open"  # unchanged
    assert ticket.final_priority is None
    db.commit.assert_called_once()


def test_update_user_ticket_skips_commit_when_no_changes(make_ticket):
    ticket = make_ticket()
    db = MagicMock()
    svc.update_user_ticket(db, ticket, {"status": "closed"})  # not whitelisted
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Ownership / authorization
# ---------------------------------------------------------------------------


def test_user_can_view_ticket_when_creator(make_ticket, user_id):
    ticket = make_ticket(created_by=user_id)
    assert svc.user_can_view_ticket(ticket, user_id) is True


def test_user_can_view_ticket_when_assignee(make_ticket, user_id, other_user_id):
    ticket = make_ticket(created_by=other_user_id, assigned_to=user_id)
    assert svc.user_can_view_ticket(ticket, user_id) is True


def test_user_cannot_view_ticket_owned_by_someone_else(
    make_ticket, user_id, other_user_id
):
    ticket = make_ticket(created_by=other_user_id, assigned_to=None)
    assert svc.user_can_view_ticket(ticket, user_id) is False
