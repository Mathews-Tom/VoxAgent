from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from voxagent.models import TenantConfig
from voxagent.server.routes.tenants import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.pool = MagicMock()
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


class TestCreateTenant:
    @patch("voxagent.server.routes.tenants.create_tenant", new_callable=AsyncMock)
    def test_create_returns_201(self, mock_create: AsyncMock) -> None:
        tenant = _make_tenant()
        mock_create.return_value = tenant
        client = TestClient(_make_app())
        resp = client.post("/api/tenants", json={"name": "Acme", "domain": "acme.com"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "Acme"

    @patch("voxagent.server.routes.tenants.create_tenant", new_callable=AsyncMock)
    def test_create_hashes_password(self, mock_create: AsyncMock) -> None:
        tenant = _make_tenant()
        mock_create.return_value = tenant
        client = TestClient(_make_app())
        client.post("/api/tenants", json={"name": "Acme", "domain": "acme.com", "password": "secret"})
        created_config = mock_create.call_args[0][1]
        assert created_config.password_hash is not None
        assert created_config.password_hash != "secret"

    def test_create_missing_name_returns_422(self) -> None:
        client = TestClient(_make_app())
        resp = client.post("/api/tenants", json={"domain": "acme.com"})
        assert resp.status_code == 422


class TestListTenants:
    @patch("voxagent.server.routes.tenants.list_tenants", new_callable=AsyncMock)
    def test_list_returns_tenants(self, mock_list: AsyncMock) -> None:
        mock_list.return_value = [_make_tenant(name="A"), _make_tenant(name="B")]
        client = TestClient(_make_app())
        resp = client.get("/api/tenants")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @patch("voxagent.server.routes.tenants.list_tenants", new_callable=AsyncMock)
    def test_list_empty(self, mock_list: AsyncMock) -> None:
        mock_list.return_value = []
        client = TestClient(_make_app())
        resp = client.get("/api/tenants")
        assert resp.json() == []


class TestGetTenant:
    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    def test_get_existing(self, mock_get: AsyncMock) -> None:
        tenant = _make_tenant()
        mock_get.return_value = tenant
        client = TestClient(_make_app())
        resp = client.get(f"/api/tenants/{tenant.id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == tenant.name

    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    def test_get_not_found(self, mock_get: AsyncMock) -> None:
        mock_get.return_value = None
        client = TestClient(_make_app())
        resp = client.get(f"/api/tenants/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestUpdateTenant:
    @patch("voxagent.server.routes.tenants.update_tenant", new_callable=AsyncMock)
    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    def test_update_returns_200(self, mock_get: AsyncMock, mock_update: AsyncMock) -> None:
        tenant = _make_tenant(name="Old")
        updated = _make_tenant(id=tenant.id, name="New")
        mock_get.return_value = tenant
        mock_update.return_value = updated
        client = TestClient(_make_app())
        resp = client.put(f"/api/tenants/{tenant.id}", json={"name": "New"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"

    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    def test_update_not_found(self, mock_get: AsyncMock) -> None:
        mock_get.return_value = None
        client = TestClient(_make_app())
        resp = client.put(f"/api/tenants/{uuid.uuid4()}", json={"name": "X"})
        assert resp.status_code == 404

    @patch("voxagent.server.routes.tenants.update_tenant", new_callable=AsyncMock)
    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    def test_partial_update_preserves_fields(self, mock_get: AsyncMock, mock_update: AsyncMock) -> None:
        tenant = _make_tenant(name="Old", greeting="Hi there")
        mock_get.return_value = tenant
        mock_update.return_value = _make_tenant(id=tenant.id, name="New", greeting="Hi there")
        client = TestClient(_make_app())
        resp = client.put(f"/api/tenants/{tenant.id}", json={"name": "New"})
        updated_config = mock_update.call_args[0][1]
        assert updated_config.greeting == "Hi there"
        assert resp.status_code == 200


class TestDeleteTenant:
    @patch("voxagent.server.routes.tenants.delete_tenant", new_callable=AsyncMock)
    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    def test_delete_returns_204(self, mock_get: AsyncMock, mock_delete: AsyncMock) -> None:
        tenant = _make_tenant()
        mock_get.return_value = tenant
        client = TestClient(_make_app())
        resp = client.delete(f"/api/tenants/{tenant.id}")
        assert resp.status_code == 204

    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    def test_delete_not_found(self, mock_get: AsyncMock) -> None:
        mock_get.return_value = None
        client = TestClient(_make_app())
        resp = client.delete(f"/api/tenants/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestGetTenantConfig:
    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    def test_get_config_returns_200(self, mock_get: AsyncMock) -> None:
        tenant = _make_tenant(greeting="Hey!", widget_color="#000", widget_position="top-left")
        mock_get.return_value = tenant
        client = TestClient(_make_app())
        resp = client.get(f"/api/tenants/{tenant.id}/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["greeting"] == "Hey!"
        assert data["widget_color"] == "#000"

    @patch("voxagent.server.routes.tenants.get_tenant", new_callable=AsyncMock)
    def test_get_config_not_found(self, mock_get: AsyncMock) -> None:
        mock_get.return_value = None
        client = TestClient(_make_app())
        resp = client.get(f"/api/tenants/{uuid.uuid4()}/config")
        assert resp.status_code == 404
