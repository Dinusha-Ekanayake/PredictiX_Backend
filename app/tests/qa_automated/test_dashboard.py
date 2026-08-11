from unittest.mock import MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_db, get_current_user, require_admin, require_user
from app.routers.admin_dashboard import admin_dashboard_router
from app.routers.warehouse_dashboard import warehouse_dashboard_router

@pytest.fixture
def dashboard_app():
    app = FastAPI()
    app.include_router(admin_dashboard_router)
    app.include_router(warehouse_dashboard_router)

    fake_db = MagicMock()
    fake_user = MagicMock()
    fake_user.id = "user-id-123"
    fake_user.role = "admin"
    fake_user.warehouse_id = "warehouse-id-123"

    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user
    app.dependency_overrides[require_user] = lambda: fake_user
    return app

@pytest.fixture
def client(dashboard_app):
    return TestClient(dashboard_app)

def test_admin_dashboard_summary_returns_cached_data(client):
    fake_summary = {"kpis": {"total_assets": 10}, "recent_tickets": []}
    
    with patch("app.routers.admin_dashboard._cache.get_or_refresh", return_value=fake_summary):
        resp = client.get("/admin-dashboard/summary")
    
    assert resp.status_code == 200
    assert resp.json() == fake_summary

def test_warehouse_dashboard_summary_returns_cached_data(client):
    fake_summary = {"avg_health_score": 85.5, "total_assets": 12}
    
    with patch("app.routers.warehouse_dashboard._cache.get_or_refresh", return_value=fake_summary):
        resp = client.get("/warehouse-dashboard/summary")
        
    assert resp.status_code == 200
    assert resp.json() == fake_summary
