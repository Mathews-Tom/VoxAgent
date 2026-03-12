from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from voxagent.models import LeadRecord
from voxagent.server.routes.leads import router

_TENANT_ID = uuid.uuid4()


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.pool = MagicMock()
    return app


def _make_lead(**overrides: object) -> LeadRecord:
    defaults: dict[str, object] = {
        "tenant_id": _TENANT_ID,
        "conversation_id": uuid.uuid4(),
        "name": "Alice",
        "email": "alice@example.com",
        "extracted_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return LeadRecord(**defaults)  # type: ignore[arg-type]


class TestGetLeads:
    @patch("voxagent.server.routes.leads.list_leads", new_callable=AsyncMock)
    def test_returns_leads_list(self, mock_list: AsyncMock) -> None:
        mock_list.return_value = [_make_lead(), _make_lead(name="Bob")]
        client = TestClient(_make_app())
        resp = client.get(f"/api/tenants/{_TENANT_ID}/leads")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @patch("voxagent.server.routes.leads.list_leads", new_callable=AsyncMock)
    def test_empty_list(self, mock_list: AsyncMock) -> None:
        mock_list.return_value = []
        client = TestClient(_make_app())
        resp = client.get(f"/api/tenants/{_TENANT_ID}/leads")
        assert resp.json() == []

    @patch("voxagent.server.routes.leads.list_leads", new_callable=AsyncMock)
    def test_respects_limit_offset(self, mock_list: AsyncMock) -> None:
        mock_list.return_value = []
        client = TestClient(_make_app())
        client.get(f"/api/tenants/{_TENANT_ID}/leads?limit=10&offset=5")
        call_kwargs = mock_list.call_args
        assert call_kwargs.kwargs["limit"] == 10
        assert call_kwargs.kwargs["offset"] == 5


class TestExportLeads:
    @patch("voxagent.server.routes.leads.list_leads", new_callable=AsyncMock)
    def test_csv_content_type_and_headers(self, mock_list: AsyncMock) -> None:
        mock_list.return_value = []
        client = TestClient(_make_app())
        resp = client.get(f"/api/tenants/{_TENANT_ID}/leads/export")
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers["content-disposition"]

    @patch("voxagent.server.routes.leads.list_leads", new_callable=AsyncMock)
    def test_csv_with_data_rows(self, mock_list: AsyncMock) -> None:
        lead = _make_lead(name="Charlie", email="c@d.com")
        mock_list.return_value = [lead]
        client = TestClient(_make_app())
        resp = client.get(f"/api/tenants/{_TENANT_ID}/leads/export")
        lines = resp.text.strip().split("\n")
        assert len(lines) == 2  # header + 1 data row
        assert "Charlie" in lines[1]
        assert "c@d.com" in lines[1]
