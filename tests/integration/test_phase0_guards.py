from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from voxagent.agent.core import VoxAgent
from voxagent.config import Config
from voxagent.models import TenantConfig
from voxagent.server.routes.widget import router as widget_router


def _make_widget_app() -> FastAPI:
    app = FastAPI()
    app.include_router(widget_router)
    config = MagicMock()
    config.livekit_api_key = "devkey"
    config.livekit_api_secret = "devsecret1234567890123456789012345678901234567890"
    config.livekit_url = "ws://localhost:7880"
    config.allow_localhost_widget_origins = True
    app.state.config = config
    app.state.pool = MagicMock()
    return app


class TestTokenLifecycleGuards:
    @patch("voxagent.server.routes.widget.get_tenant", new_callable=AsyncMock)
    def test_token_rejects_unknown_tenant(self, mock_get_tenant: AsyncMock) -> None:
        mock_get_tenant.return_value = None
        client = TestClient(_make_widget_app())

        response = client.post("/api/token", json={"tenant_id": str(uuid.uuid4())})

        assert response.status_code == 404
        assert response.json()["detail"] == "Tenant not found"

    @patch("voxagent.server.routes.widget.get_tenant", new_callable=AsyncMock)
    def test_token_succeeds_for_existing_tenant(self, mock_get_tenant: AsyncMock) -> None:
        tenant_id = uuid.uuid4()
        mock_get_tenant.return_value = TenantConfig(
            id=tenant_id,
            name="Acme",
            domain="acme.example",
        )
        client = TestClient(_make_widget_app())

        response = client.post(
            "/api/token",
            json={"tenant_id": str(tenant_id)},
            headers={"origin": "http://localhost:3000"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["room_name"].startswith(str(tenant_id))
        assert body["visitor_id"]


@pytest.mark.asyncio
async def test_voxagent_transcript_capture_forms_persisted_session_payload(app_config: Config) -> None:
    with (
        patch("voxagent.agent.core.create_stt", return_value=MagicMock()),
        patch("voxagent.agent.core.create_llm", return_value=MagicMock()),
        patch("voxagent.agent.core.create_tts", return_value=MagicMock()),
        patch("voxagent.agent.core.silero.VAD.load", return_value=MagicMock()),
    ):
        agent = VoxAgent(
            tenant_config=TenantConfig(name="Acme", domain="acme.example"),
            app_config=app_config,
        )

        agent.on_user_transcript("Hello")
        agent.on_agent_transcript("Hi, how can I help?")

        events = agent.conversation_events()
        transcript = agent.transcript()

        assert [event.role for event in events] == ["user", "assistant"]
        assert transcript == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi, how can I help?"},
        ]
