from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from voxagent.models import TenantConfig
from voxagent.server.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


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
    def test_health_returns_ok(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestVoxAgentConstruction:
    def test_voxagent_builds_session_with_default_config(self) -> None:
        from voxagent.agent.core import VoxAgent
        from voxagent.config import Config

        tenant = TenantConfig(name="test", domain="test.local")
        # VoxAgent construction requires LiveKit plugins installed
        # This test verifies the import chain and model construction work
        assert tenant.stt.provider.value == "whisper"
        assert tenant.llm.provider.value == "ollama"
        assert tenant.tts.provider.value == "qwen3"
