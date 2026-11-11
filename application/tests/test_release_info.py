"""No live database required; DATABASE_URL is a syntactically valid test URL."""
from fastapi.testclient import TestClient
from app.main import app


def test_version_route_is_registered(monkeypatch):
    monkeypatch.setenv("HOSTNAME", "test-api-pod")
    with TestClient(app) as client:
        response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "week14-v2", "pod": "test-api-pod"}
    assert response.headers["cache-control"] == "no-store"


def test_existing_root_contract_is_preserved():
    with TestClient(app) as client:
        assert client.get("/").json() == {"status": "API is running"}
        assert client.get("/health").json() == {"status": "healthy"}
