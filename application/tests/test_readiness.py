"""Offline unit tests: mock the DB instead of touching the lab database."""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app import readiness
from app.main import app


def test_ready_returns_200_when_database_answers(monkeypatch):
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.return_value = 1
    monkeypatch.setattr(readiness, "readiness_engine", engine)

    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert response.headers["cache-control"] == "no-store"
    assert str(connection.execute.call_args.args[0]) == "SELECT 1"
    engine.connect.return_value.__exit__.assert_called_once()


def test_ready_returns_503_without_leaking_driver_details(monkeypatch):
    engine = MagicMock()
    engine.connect.side_effect = SQLAlchemyError("private_password_DO_NOT_LEAK")
    monkeypatch.setattr(readiness, "readiness_engine", engine)

    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}
    assert "private_password" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_health_does_not_depend_on_database(monkeypatch):
    engine = MagicMock()
    engine.connect.side_effect = SQLAlchemyError("database unavailable")
    monkeypatch.setattr(readiness, "readiness_engine", engine)

    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    engine.connect.assert_not_called()
