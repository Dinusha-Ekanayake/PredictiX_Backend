import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_db, get_current_user, require_user
from app.routers.notification_preferences import router as settings_router

@pytest.fixture
def settings_app():
    app = FastAPI()
    app.include_router(settings_router)

    fake_db = MagicMock()
    fake_user = MagicMock()
    fake_user.role = "user"

    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[require_user] = lambda: fake_user
    # The endpoints scope results to the caller, so they resolve the caller
    # themselves rather than relying on the router-level require_user gate.
    app.dependency_overrides[get_current_user] = lambda: fake_user
    return app

@pytest.fixture
def client(settings_app):
    return TestClient(settings_app)

def test_list_notification_preferences_returns_list(client, settings_app):
    fake_db = settings_app.dependency_overrides[get_db]()
    
    # Field names and values must satisfy UserNotificationPreferenceOut:
    # notification_type is a fixed set, and the flag is `enabled`.
    mock_pref = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        notification_type="high_risk_asset",
        channel="email",
        enabled=True,
    )

    # A non-admin caller is scoped to their own rows, so the handler adds a
    # filter() before paginating. Return the same mock from filter() so the
    # whole chain resolves.
    mock_query = fake_db.query.return_value
    mock_query.filter.return_value = mock_query
    mock_query.offset.return_value.limit.return_value.all.return_value = [mock_pref]
    
    resp = client.get("/notification-preferences/")
    
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["channel"] == "email"
