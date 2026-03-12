from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from voxagent.models import TenantConfig
from voxagent.server.routes.widget import router as widget_router


def _make_test_app() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(widget_router)

    config = MagicMock()
    config.livekit_api_key = "devkey"
    config.livekit_api_secret = "devsecret1234567890123456789012345678901234567890"
    config.livekit_url = "ws://localhost:7880"
    test_app.state.config = config

    return test_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_test_app())


class TestTokenEndpoint:
    def test_create_token_returns_jwt_and_room_name(self, client: TestClient) -> None:
        response = client.post(
            "/api/token",
            json={"tenant_id": str(uuid.uuid4())},
        )
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "room_name" in data
        assert "livekit_url" in data
        assert "visitor_id" in data

    def test_create_token_room_name_contains_tenant_id(self, client: TestClient) -> None:
        tenant_id = str(uuid.uuid4())
        response = client.post(
            "/api/token",
            json={"tenant_id": tenant_id},
        )
        data = response.json()
        assert data["room_name"].startswith(tenant_id)

    def test_create_token_generates_unique_visitor_ids(self, client: TestClient) -> None:
        tenant_id = str(uuid.uuid4())
        responses = [
            client.post("/api/token", json={"tenant_id": tenant_id}).json()
            for _ in range(3)
        ]
        visitor_ids = [r["visitor_id"] for r in responses]
        assert len(set(visitor_ids)) == 3

    def test_create_token_missing_tenant_id_returns_422(self, client: TestClient) -> None:
        response = client.post("/api/token", json={})
        assert response.status_code == 422


class TestHealthEndpoint:
    @pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL not set — requires live database",
    )
    def test_health_returns_ok(self) -> None:
        from voxagent.server.app import app as real_app

        with TestClient(real_app) as c:
            response = c.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestVoxAgentConstruction:
    def test_tenant_config_has_correct_defaults(self) -> None:
        tenant = TenantConfig(name="test", domain="test.local")
        assert tenant.stt.provider.value == "whisper"
        assert tenant.llm.provider.value == "ollama"
        assert tenant.tts.provider.value == "qwen3"
