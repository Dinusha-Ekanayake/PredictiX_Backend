import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_db, require_user, require_admin
from app.routers.warehouses import router as warehouses_router

@pytest.fixture
def wh_app():
    app = FastAPI()
    app.include_router(warehouses_router)

    fake_db = MagicMock()
    fake_user = MagicMock()

    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[require_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user
    return app

@pytest.fixture
def client(wh_app):
    return TestClient(wh_app)

def test_list_warehouses_returns_list(client, wh_app):
    fake_db = wh_app.dependency_overrides[get_db]()
    
    mock_wh = SimpleNamespace(
        id=uuid.uuid4(),
        code="WH-001",
        name="Colombo Warehouse",
        address="123 Main St",
        city="Colombo",
        district="Colombo",
        country="Sri Lanka",
        climate_zone="Wet",
        warehouse_type="Logistics"
    )
    
    mock_query = fake_db.query.return_value
    mock_query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [mock_wh]
    
    resp = client.get("/warehouses/")
    
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Colombo Warehouse"

def test_get_warehouse_returns_not_found(client, wh_app):
    fake_db = wh_app.dependency_overrides[get_db]()
    
    mock_query = fake_db.query.return_value
    mock_query.filter.return_value.first.return_value = None
    
    resp = client.get(f"/warehouses/{uuid.uuid4()}")
    
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Warehouse not found"
