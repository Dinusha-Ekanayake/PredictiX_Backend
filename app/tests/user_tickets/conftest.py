"""Shared fixtures for user-ticket tests.

The production models depend on PostgreSQL-specific types (UUID, JSONB), so
we stub the DB with `unittest.mock` rather than spinning up SQLite. The
tests below focus on routing + service-layer logic with the DB and AI
services mocked.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def other_user_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_ticket(**overrides):
    """Build a minimal SimpleNamespace that quacks like a Ticket ORM object."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        ticket_number="TKT-2026-0001",
        title="Forklift overheating",
        description="Engine temp warning during morning shift.",
        status="open",
        priority="medium",
        predicted_priority=None,
        final_priority=None,
        predicted_category=None,
        final_category=None,
        ticket_summary=None,
        asset_summary=None,
        asset_id=None,
        warehouse_id=None,
        created_by=uuid.uuid4(),
        assigned_to=None,
        reviewed_by=None,
        opened_at=now,
        reviewed_at=None,
        resolved_at=None,
        closed_at=None,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def make_ticket():
    return _make_ticket


@pytest.fixture
def make_profile():
    def _make(user_id: uuid.UUID, *, email: str = "user@example.com", role: str = "user"):
        return SimpleNamespace(
            id=user_id,
            email=email,
            role=role,
            full_name="Test User",
            phone=None,
            status="active",
            warehouse_id=None,
            department_id=None,
            meta={},
            employee_id=f"EMP-{str(user_id)[:8]}",
        )

    return _make
