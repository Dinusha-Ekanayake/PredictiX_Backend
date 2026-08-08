from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_db, get_current_user, require_user, require_admin
from app.routers.assets import router as assets_router

@pytest.fixture
def asset_app():
    app = FastAPI()
    app.include_router(assets_router)

    fake_db = MagicMock()
    fake_user = MagicMock()
    fake_user.id = "user-id-456"
    fake_user.role = "admin"
    fake_user.warehouse_id = "warehouse-id-456"

    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user
    return app

@pytest.fixture
def client(asset_app):
    return TestClient(asset_app)

def test_list_assets_dropdown_returns_mapped_list(client, asset_app):
    fake_db = asset_app.dependency_overrides[get_db]()
    
    mock_asset = MagicMock()
    mock_asset.id = "some-uuid"
    mock_asset.asset_code = "AST-001"
    mock_asset.asset_name = "Forklift"
    mock_asset.asset_type = "Logistics"
    mock_asset.warehouse_id = "some-warehouse-uuid"
    
    # Configure mock query chain
    mock_query = fake_db.query.return_value
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value.all.return_value = [mock_asset]
    
    resp = client.get("/assets/dropdown")
    
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["asset_code"] == "AST-001"
    assert data[0]["asset_name"] == "Forklift"
