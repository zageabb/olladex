from starlette.requests import Request
from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.main import app, is_loopback_client


def request_from(host: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/status",
        "headers": [],
        "client": (host, 12345),
        "server": ("olladex", 8001),
        "scheme": "http",
        "query_string": b"",
    })


def test_loopback_clients_are_recognized():
    assert is_loopback_client(request_from("127.0.0.1"))
    assert is_loopback_client(request_from("::1"))
    assert is_loopback_client(request_from("::ffff:127.0.0.1"))


def test_non_loopback_clients_are_not_trusted():
    assert not is_loopback_client(request_from("192.168.1.25"))
    assert not is_loopback_client(request_from("testclient"))


def test_loopback_api_request_does_not_require_token():
    client = TestClient(app, client=("127.0.0.1", 12345), headers={})
    assert client.get("/api/status").status_code == 200


def test_non_loopback_api_request_still_requires_token():
    client = TestClient(app, client=("192.168.1.25", 12345), headers={})
    assert client.get("/api/status").status_code == 401
    response = client.get("/api/status", headers={"Authorization": f"Bearer {settings.api_token}"})
    assert response.status_code == 200
