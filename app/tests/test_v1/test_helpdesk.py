from unittest.mock import MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.faqs import router as faqs_router

@pytest.fixture
def faq_app():
    app = FastAPI()
    app.include_router(faqs_router)
    return app

@pytest.fixture
def client(faq_app):
    return TestClient(faq_app)

def test_list_faqs_calls_supabase(client):
    mock_data = [{
        "id": "faq-1",
        "question": "What is PredictiX?",
        "answer": "PredictiX is an AI platform.",
        "category": "General",
        "tags": [],
        "is_active": True,
        "created_at": "2026-08-06T12:00:00Z",
        "updated_at": "2026-08-06T12:00:00Z"
    }]
    
    mock_resp = MagicMock()
    mock_resp.data = mock_data
    
    mock_chain = MagicMock()
    mock_chain.select.return_value = mock_chain
    mock_chain.eq.return_value = mock_chain
    mock_chain.order.return_value.execute.return_value = mock_resp
    
    with patch("app.routers.faqs.supabase.from_", return_value=mock_chain):
        resp = client.get("/faqs/")
        
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["question"] == "What is PredictiX?"
