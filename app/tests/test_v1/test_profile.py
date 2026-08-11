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
    fake_db = profile_app.dependency_overrides[get_db]()
    fake_user = profile_app.dependency_overrides[get_current_user]()
    
    mock_profile = SimpleNamespace(
        id=fake_user.id,
        email="john@example.com",
        full_name="John Doe",
        phone="1234",
        status="active",
        role="user",
        employee_id="EMP-001",
        department_id=uuid.uuid4(),
        warehouse_id=uuid.uuid4(),
        avatar_url=None,
        meta={}
    )
    
    mock_dept = SimpleNamespace(id=mock_profile.department_id, name="Eng")
    mock_wh = SimpleNamespace(id=mock_profile.warehouse_id, name="Colombo")
    
    # First query fetches Profile, second fetches Department, third fetches Warehouse
    fake_db.query.return_value.filter.return_value.first.side_effect = [mock_profile, mock_dept, mock_wh]
    fake_db.query.return_value.filter.return_value.all.return_value = []
    
    resp = client.get("/profiles/me")
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "john@example.com"
    assert data["firstName"] == "John"
