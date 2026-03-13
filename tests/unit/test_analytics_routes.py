from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from voxagent.models import AdminRole, AuthContext
from voxagent.server.auth import require_auth_context
from voxagent.server.routes.analytics import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.pool = MagicMock()
    return app


def _tenant_admin_context(tenant_id: uuid.UUID) -> AuthContext:
    return AuthContext(
        admin_user_id=uuid.uuid4(),
        email="tenant-admin@example.com",
        tenant_roles={tenant_id: AdminRole.TENANT_ADMIN},
    )


class TestAnalyticsRoutes:
    @patch("voxagent.server.routes.analytics._get_analytics", new_callable=AsyncMock)
    def test_analytics_page_renders_job_backlog_and_failures(
        self,
        mock_get_analytics: AsyncMock,
    ) -> None:
        tenant_id = uuid.uuid4()
        mock_get_analytics.return_value = {
            "total_conversations": 20,
            "total_leads": 6,
            "avg_duration": 125.0,
            "by_language": {"en": 14, "hi": 6},
            "over_time": [{"day": "2026-03-10", "cnt": 4}],
            "top_intents": [{"intent": "demo", "cnt": 3}],
            "job_status_counts": {
                "pending": 2,
                "running": 1,
                "failed": 0,
                "dead_letter": 1,
                "succeeded": 12,
            },
            "recent_job_failures": [
                {
                    "job_type": "lead_webhook",
                    "last_error": "timeout",
                    "updated_at": "2026-03-13T13:30:00+00:00",
                }
            ],
        }
        app = _make_app()
        app.dependency_overrides[require_auth_context] = lambda: _tenant_admin_context(tenant_id)
        client = TestClient(app)

        response = client.get(f"/dashboard/{tenant_id}/analytics")

        assert response.status_code == 200
        assert "Queued Jobs" in response.text
        assert "Dead Letters" in response.text
        assert "lead_webhook" in response.text
        assert "timeout" in response.text
