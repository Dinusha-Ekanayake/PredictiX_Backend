import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_db, get_current_user, require_user, require_admin
from app.routers.profile import router as profiles_router

@pytest.fixture
def profile_app():
    app = FastAPI()
    app.include_router(profiles_router)

    fake_db = MagicMock()
    fake_user = MagicMock()
    fake_user.id = uuid.uuid4()
    fake_user.role = "user"
    fake_user.warehouse_id = "00000000-0000-0000-0000-000000000000"

    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user
    return app

@pytest.fixture
def client(profile_app):
    return TestClient(profile_app)

def test_get_my_profile(client, profile_app):
    """GET /profiles/me returns the caller's own profile.

    The handler reads the identity straight off current_user, which
    get_current_user has already loaded, and resolves the department name,
    warehouse name and assigned-asset count in a single db.execute(). It used
    to re-select the profile by email and then run three more ORM queries;
    against Supabase each of those was a separate ~250ms round trip.
    """
    fake_db = profile_app.dependency_overrides[get_db]()
    fake_user = profile_app.dependency_overrides[get_current_user]()

    # current_user is the source of identity now, so the fixture carries it.
    fake_user.email = "john@example.com"
    fake_user.full_name = "John Doe"
    fake_user.phone = "1234"
    fake_user.status = "active"
    fake_user.role = "user"
    fake_user.employee_id = "EMP-001"
    fake_user.department_id = uuid.uuid4()
    fake_user.warehouse_id = uuid.uuid4()
    fake_user.avatar_url = None
    fake_user.meta = {}

    # One statement returns (department_name, warehouse_name, asset_count).
    fake_db.execute.return_value.first.return_value = ("Eng", "Colombo", 0)

    resp = client.get("/profiles/me")

    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "john@example.com"
    assert data["firstName"] == "John"
    assert data["department"] == "Eng"
    assert data["warehouse"] == "Colombo"
    assert data["assignedAssetsCount"] == 0
    # The point of the change: one round trip, not four.
    assert fake_db.execute.call_count == 1, (
        f"expected a single statement, got {fake_db.execute.call_count}")
