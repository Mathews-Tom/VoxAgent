from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from voxagent.models import AdminRole, AuthContext
from voxagent.server.auth import require_auth_context
from voxagent.server.routes.knowledge import router


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


class TestKnowledgeRoutes:
    @patch("voxagent.server.routes.knowledge.list_sources", new_callable=AsyncMock)
    def test_knowledge_page_renders_source_metadata(self, mock_list_sources: AsyncMock) -> None:
        tenant_id = uuid.uuid4()
        mock_list_sources.return_value = [
            {
                "name": "https://docs.acme.com/start",
                "title": "Getting Started",
                "source_type": "website",
                "source_version_id": "version-12345678",
                "chunk_count": 3,
            }
        ]
        app = _make_app()
        app.dependency_overrides[require_auth_context] = lambda: _tenant_admin_context(tenant_id)
        client = TestClient(app)

        response = client.get(f"/dashboard/{tenant_id}/knowledge")

        assert response.status_code == 200
        assert "Getting Started" in response.text
        assert "3 chunks" in response.text
        assert "version version-" in response.text

    @patch("voxagent.server.routes.knowledge.rebuild_index", new_callable=AsyncMock)
    @patch("voxagent.server.routes.knowledge.list_sources", new_callable=AsyncMock)
    def test_reindex_rebuilds_and_shows_success_banner(
        self,
        mock_list_sources: AsyncMock,
        mock_rebuild_index: AsyncMock,
    ) -> None:
        tenant_id = uuid.uuid4()
        mock_list_sources.return_value = []
        app = _make_app()
        app.dependency_overrides[require_auth_context] = lambda: _tenant_admin_context(tenant_id)
        client = TestClient(app)

        response = client.post(f"/dashboard/{tenant_id}/knowledge/reindex")

        assert response.status_code == 200
        mock_rebuild_index.assert_awaited_once()
        assert "Knowledge index rebuilt successfully." in response.text

    @patch("voxagent.server.routes.knowledge.crawl_website", new_callable=AsyncMock)
    @patch("voxagent.server.routes.knowledge.ingest_pages_service", new_callable=AsyncMock)
    @patch("voxagent.server.routes.knowledge.list_sources", new_callable=AsyncMock)
    def test_recrawl_ingests_pages_and_shows_success_banner(
        self,
        mock_list_sources: AsyncMock,
        mock_ingest_pages: AsyncMock,
        mock_crawl_website: AsyncMock,
    ) -> None:
        tenant_id = uuid.uuid4()
        mock_list_sources.return_value = []
        mock_crawl_website.return_value = [MagicMock()]
        app = _make_app()
        app.dependency_overrides[require_auth_context] = lambda: _tenant_admin_context(tenant_id)
        client = TestClient(app)

        response = client.post(
            f"/dashboard/{tenant_id}/knowledge/recrawl",
            data={"source": "https://docs.acme.com/start"},
        )

        assert response.status_code == 200
        mock_crawl_website.assert_awaited_once_with("https://docs.acme.com/start")
        mock_ingest_pages.assert_awaited_once()
        assert "Source re-crawled and index rebuilt successfully." in response.text

    @patch("voxagent.server.routes.knowledge.delete_source_service", new_callable=AsyncMock)
    @patch("voxagent.server.routes.knowledge.list_sources", new_callable=AsyncMock)
    def test_delete_marks_source_removed_and_shows_success_banner(
        self,
        mock_list_sources: AsyncMock,
        mock_delete_source: AsyncMock,
    ) -> None:
        tenant_id = uuid.uuid4()
        mock_list_sources.return_value = []
        app = _make_app()
        app.dependency_overrides[require_auth_context] = lambda: _tenant_admin_context(tenant_id)
        client = TestClient(app)

        response = client.post(
            f"/dashboard/{tenant_id}/knowledge/delete",
            data={"source": "https://docs.acme.com/start"},
        )

        assert response.status_code == 200
        mock_delete_source.assert_awaited_once_with(
            app.state.pool,
            tenant_id,
            "https://docs.acme.com/start",
        )
        assert "Source removed and index rebuilt successfully." in response.text
