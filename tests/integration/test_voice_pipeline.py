from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
    config.allow_localhost_widget_origins = True
    test_app.state.config = config
    test_app.state.pool = MagicMock()

    return test_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_test_app())


class TestTokenEndpoint:
    @patch("voxagent.server.routes.widget.get_tenant", new_callable=AsyncMock)
    def test_create_token_returns_jwt_and_room_name(
        self,
        mock_get_tenant: AsyncMock,
        client: TestClient,
    ) -> None:
        tenant_id = uuid.uuid4()
        mock_get_tenant.return_value = TenantConfig(id=tenant_id, name="Acme", domain="acme.local")

        response = client.post(
            "/api/token",
            json={"tenant_id": str(tenant_id)},
            headers={"origin": "http://localhost:3000"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "room_name" in data
        assert "livekit_url" in data
        assert "visitor_id" in data

    @patch("voxagent.server.routes.widget.get_tenant", new_callable=AsyncMock)
    def test_create_token_room_name_contains_tenant_id(
        self,
        mock_get_tenant: AsyncMock,
        client: TestClient,
    ) -> None:
        tenant_id = uuid.uuid4()
        mock_get_tenant.return_value = TenantConfig(id=tenant_id, name="Acme", domain="acme.local")

        response = client.post(
            "/api/token",
            json={"tenant_id": str(tenant_id)},
            headers={"origin": "http://localhost:3000"},
        )

        assert response.json()["room_name"].startswith(str(tenant_id))

    @patch("voxagent.server.routes.widget.get_tenant", new_callable=AsyncMock)
    def test_create_token_generates_unique_visitor_ids(
        self,
        mock_get_tenant: AsyncMock,
        client: TestClient,
    ) -> None:
        tenant_id = uuid.uuid4()
        mock_get_tenant.return_value = TenantConfig(id=tenant_id, name="Acme", domain="acme.local")

        responses = [
            client.post(
                "/api/token",
                json={"tenant_id": str(tenant_id)},
                headers={"origin": "http://localhost:3000"},
            ).json()
            for _ in range(3)
        ]
        visitor_ids = [response["visitor_id"] for response in responses]
        assert len(set(visitor_ids)) == 3

    def test_create_token_missing_tenant_id_returns_422(self, client: TestClient) -> None:
        response = client.post("/api/token", json={})
        assert response.status_code == 422


class TestHealthEndpoint:
    @pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL not set — requires live database",
    )
    def test_liveness_returns_ok(self) -> None:
        from voxagent.server.app import app as real_app

        with TestClient(real_app) as c:
            response = c.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
