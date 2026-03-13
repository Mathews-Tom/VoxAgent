from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from voxagent.models import AdminRole, AdminUser, AuthContext, TenantConfig
from voxagent.server.auth import require_auth_context, require_platform_admin
from voxagent.server.routes.tenants import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.pool = MagicMock()
    app.state.config = MagicMock(allow_localhost_widget_origins=True)
    return app


def _make_tenant(**overrides: object) -> TenantConfig:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Acme",
        "domain": "acme.com",
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return TenantConfig(**defaults)  # type: ignore[arg-type]


def _tenant_admin_context(tenant_id: uuid.UUID) -> AuthContext:
    return AuthContext(
        admin_user_id=uuid.uuid4(),
        email="tenant-admin@example.com",
        tenant_roles={tenant_id: AdminRole.TENANT_ADMIN},
    )


def _platform_admin_context() -> AuthContext:
    return AuthContext(
        admin_user_id=uuid.uuid4(),
        email="platform-admin@example.com",
        is_platform_admin=True,
    )


class TestPublicCreateTenant:
    @patch("voxagent.server.routes.tenants.create_tenant_with_admin", new_callable=AsyncMock)
    def test_create_returns_201(self, mock_create: AsyncMock) -> None:
        tenant = _make_tenant()
        admin = AdminUser(email="owner@example.com", password_hash="hash")
        mock_create.return_value = (tenant, admin, MagicMock())
        client = TestClient(_make_app())

        response = client.post(
            "/api/public/tenants",
            json={
                "name": "Acme",
                "domain": "acme.com",
                "admin_email": "owner@example.com",
                "password": "secret123",
            },
        )

        assert response.status_code == 201
        assert response.json()["name"] == "Acme"

    def test_create_missing_name_returns_422(self) -> None:
        client = TestClient(_make_app())
        response = client.post(
            "/api/public/tenants",
            json={"domain": "acme.com", "admin_email": "owner@example.com", "password": "secret123"},
        )
        assert response.status_code == 422


class TestProtectedTenantCrud:
    @patch("voxagent.server.routes.tenants.list_tenants", new_callable=AsyncMock)
    def test_list_requires_platform_admin(self, mock_list: AsyncMock) -> None:
        mock_list.return_value = [_make_tenant(name="A"), _make_tenant(name="B")]
        app = _make_app()
        app.dependency_overrides[require_platform_admin] = _platform_admin_context
        client = TestClient(app)

        response = client.get("/api/tenants")

        assert response.status_code == 200
        assert len(response.json()) == 2

    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    def test_get_requires_tenant_access(self, mock_get: AsyncMock) -> None:
        tenant = _make_tenant()
        mock_get.return_value = tenant
        app = _make_app()
        app.dependency_overrides[require_auth_context] = lambda: _tenant_admin_context(tenant.id)
        client = TestClient(app)

        response = client.get(f"/api/tenants/{tenant.id}")

        assert response.status_code == 200
        assert response.json()["name"] == tenant.name

    @patch("voxagent.server.routes.tenants.update_tenant", new_callable=AsyncMock)
    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    @patch("voxagent.server.routes.tenants.create_config_audit_log", new_callable=AsyncMock)
    def test_update_audits_mutation(
        self,
        mock_audit: AsyncMock,
        mock_get: AsyncMock,
        mock_update: AsyncMock,
    ) -> None:
        tenant = _make_tenant(name="Old")
        updated = _make_tenant(id=tenant.id, name="New")
        mock_get.return_value = tenant
        mock_update.return_value = updated
        app = _make_app()
        app.dependency_overrides[require_auth_context] = lambda: _tenant_admin_context(tenant.id)
        client = TestClient(app)

        response = client.put(f"/api/tenants/{tenant.id}", json={"name": "New"})

        assert response.status_code == 200
        assert response.json()["name"] == "New"
        mock_audit.assert_called_once()

    @patch("voxagent.server.routes.tenants.delete_tenant", new_callable=AsyncMock)
    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    @patch("voxagent.server.routes.tenants.create_config_audit_log", new_callable=AsyncMock)
    def test_delete_requires_platform_admin(
        self,
        mock_audit: AsyncMock,
        mock_get: AsyncMock,
        mock_delete: AsyncMock,
    ) -> None:
        tenant = _make_tenant()
        mock_get.return_value = tenant
        app = _make_app()
        app.dependency_overrides[require_platform_admin] = _platform_admin_context
        client = TestClient(app)

        response = client.delete(f"/api/tenants/{tenant.id}")

        assert response.status_code == 204
        mock_delete.assert_called_once()
        mock_audit.assert_called_once()

    @patch("voxagent.server.routes.tenants.ensure_widget_origin_allowed", new_callable=AsyncMock)
    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    def test_public_config_requires_origin_guard(
        self,
        mock_get: AsyncMock,
        mock_origin_guard: AsyncMock,
    ) -> None:
        tenant = _make_tenant(greeting="Hey!", widget_color="#000", widget_position="top-left")
        mock_get.return_value = tenant
        client = TestClient(_make_app())

        response = client.get(
            f"/api/tenants/{tenant.id}/config",
            headers={"origin": "https://acme.com"},
        )

        assert response.status_code == 200
        mock_origin_guard.assert_called_once()
