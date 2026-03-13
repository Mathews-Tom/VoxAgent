from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer

from voxagent.models import AdminRole, AdminUser, TenantMembership
from voxagent.server.auth import (
    _COOKIE_NAME,
    hash_password,
    password_hash_version,
    require_auth,
    router,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    @app.get("/api/protected")
    async def protected(tenant_id: uuid.UUID = Depends(require_auth)) -> dict[str, str]:
        return {"tenant_id": str(tenant_id)}

    app.state.pool = MagicMock()
    config = MagicMock()
    config.session_secret = "test-secret"
    app.state.config = config
    return app


def _make_admin(email: str = "admin@example.com", password: str = "pass123") -> AdminUser:
    return AdminUser(email=email, password_hash=hash_password(password))


def _make_membership(admin_user_id: uuid.UUID, tenant_id: uuid.UUID) -> TenantMembership:
    return TenantMembership(
        admin_user_id=admin_user_id,
        tenant_id=tenant_id,
        role=AdminRole.TENANT_ADMIN,
    )


def _sign_cookie(admin_user_id: uuid.UUID, tenant_id: uuid.UUID, secret: str = "test-secret") -> str:
    serializer = URLSafeTimedSerializer(secret, salt="voxagent-session")
    return serializer.dumps(
        {
            "admin_user_id": str(admin_user_id),
            "email": "admin@example.com",
            "tenant_roles": {str(tenant_id): AdminRole.TENANT_ADMIN.value},
            "is_platform_admin": False,
        }
    )


class TestLoginPage:
    def test_get_returns_200(self) -> None:
        client = TestClient(_make_app())
        response = client.get("/dashboard/login")
        assert response.status_code == 200


class TestLogin:
    @patch("voxagent.server.auth.list_tenant_memberships", new_callable=AsyncMock)
    @patch("voxagent.server.auth.get_admin_user_by_email", new_callable=AsyncMock)
    def test_valid_login_redirects(
        self,
        mock_get_admin: AsyncMock,
        mock_memberships: AsyncMock,
    ) -> None:
        tenant_id = uuid.uuid4()
        admin = _make_admin()
        mock_get_admin.return_value = admin
        mock_memberships.return_value = [_make_membership(admin.id, tenant_id)]
        client = TestClient(_make_app(), follow_redirects=False)

        response = client.post(
            "/dashboard/login",
            data={"email": admin.email, "password": "pass123"},
        )

        assert response.status_code == 303
        assert response.headers["location"].endswith(f"/dashboard/{tenant_id}/conversations")
        assert _COOKIE_NAME in response.cookies

    @patch("voxagent.server.auth.get_admin_user_by_email", new_callable=AsyncMock)
    def test_invalid_password_returns_401(self, mock_get_admin: AsyncMock) -> None:
        mock_get_admin.return_value = _make_admin()
        client = TestClient(_make_app())

        response = client.post(
            "/dashboard/login",
            data={"email": "admin@example.com", "password": "wrong"},
        )

        assert response.status_code == 401

    @patch("voxagent.server.auth.get_admin_user_by_email", new_callable=AsyncMock)
    def test_nonexistent_admin_returns_401(self, mock_get_admin: AsyncMock) -> None:
        mock_get_admin.return_value = None
        client = TestClient(_make_app())

        response = client.post(
            "/dashboard/login",
            data={"email": "missing@example.com", "password": "pass123"},
        )

        assert response.status_code == 401

    @patch("voxagent.server.auth.update_admin_user_password", new_callable=AsyncMock)
    @patch("voxagent.server.auth.list_tenant_memberships", new_callable=AsyncMock)
    @patch("voxagent.server.auth.get_admin_user_by_email", new_callable=AsyncMock)
    def test_legacy_hash_upgrades_on_login(
        self,
        mock_get_admin: AsyncMock,
        mock_memberships: AsyncMock,
        mock_update_password: AsyncMock,
    ) -> None:
        tenant_id = uuid.uuid4()
        legacy_admin = AdminUser(
            email="legacy@example.com",
            password_hash="sha256$" + "e6c3da5b206634d7f3f3586d747ffdb3b5e2f0f0f0e7f53d4f64bca93580c8f0",
            password_hash_version="sha256",
        )
        upgraded_admin = _make_admin(email=legacy_admin.email)
        mock_get_admin.return_value = legacy_admin
        mock_update_password.return_value = upgraded_admin
        mock_memberships.return_value = [_make_membership(legacy_admin.id, tenant_id)]
        client = TestClient(_make_app(), follow_redirects=False)

        with patch("voxagent.server.auth.verify_password", return_value=True):
            response = client.post(
                "/dashboard/login",
                data={"email": legacy_admin.email, "password": "pass123"},
            )

        assert response.status_code == 303
        mock_update_password.assert_called_once()
        assert password_hash_version(mock_update_password.call_args.kwargs["password_hash"]) == "argon2id"


class TestRequireAuth:
    def test_missing_cookie_api_returns_401(self) -> None:
        client = TestClient(_make_app())
        response = client.get("/api/protected")
        assert response.status_code == 401

    def test_missing_cookie_browser_returns_302(self) -> None:
        client = TestClient(_make_app())
        response = client.get(
            "/api/protected",
            headers={"accept": "text/html"},
            follow_redirects=False,
        )
        assert response.status_code == 302

    @patch("voxagent.server.auth.get_admin_user", new_callable=AsyncMock)
    def test_valid_cookie_returns_tenant_id(self, mock_get_admin: AsyncMock) -> None:
        tenant_id = uuid.uuid4()
        admin = _make_admin()
        mock_get_admin.return_value = admin
        client = TestClient(_make_app())
        client.cookies.set(_COOKIE_NAME, _sign_cookie(admin.id, tenant_id))

        response = client.get("/api/protected")

        assert response.status_code == 200
        assert response.json()["tenant_id"] == str(tenant_id)
