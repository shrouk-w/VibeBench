import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.settings import Settings


def test_health():
    with TestClient(create_app(Settings(sandbox_enabled=False))) as client:
        assert client.get("/api/health/live").json() == {"status": "ok"}
        assert client.get("/api/health/ready").json() == {
            "status": "ok",
            "execution_enabled": False,
        }


def test_public_launch_fails_closed():
    with pytest.raises(ValidationError, match="Public launch is gated"):
        Settings(public=True)
