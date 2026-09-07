import pytest
from fastapi.testclient import TestClient
from backend.app.config import settings
from backend.app.api import app  # Assemble the canonical API before any test client starts.

@pytest.fixture(autouse=True)
def authenticated_test_clients(monkeypatch):
    monkeypatch.setattr(settings, 'api_token', 'test-token')
    original = TestClient.__init__
    def initialize(self, *args, **kwargs):
        kwargs.setdefault('headers', {'Authorization': 'Bearer test-token'})
        original(self, *args, **kwargs)
    monkeypatch.setattr(TestClient, '__init__', initialize)
