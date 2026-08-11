import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_db, get_current_user, require_user, require_admin
from app.routers.users import router as users_router

@pytest.fixture
def users_app():
    app = FastAPI()
    app.include_router(users_router)

    fake_db = MagicMock()
    fake_user = MagicMock()
    fake_user.id = "user-id-789"
    fake_user.role = "admin"
    fake_user.warehouse_id = "00000000-0000-0000-0000-000000000000"  # valid UUID

    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user
    return app

@pytest.fixture
def client(users_app):
    return TestClient(users_app)

def test_list_users_returns_mapped_list(client, users_app):
    mock_profile = SimpleNamespace(
        id=uuid.uuid4(),
        email="john.doe@example.com",
        full_name="John Doe",
        phone="123456",
        role="user",
        status="active",
        employee_id="EMP-12345",
        warehouse_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        meta={}
    )
    
    with patch("app.routers.users.get_warehouse_names", return_value={}), \
         patch("app.routers.users.get_department_names", return_value={}), \
         patch("app.routers.users._fetch_users", return_value=[mock_profile]), \
         patch("app.routers.users._fetch_asset_counts", return_value={}):
        resp = client.get("/users/")
        
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["email"] == "john.doe@example.com"
    assert data[0]["name"] == "John Doe"
