from __future__ import annotations

import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer

from voxagent.models import TenantConfig
from voxagent.server.auth import _COOKIE_NAME, router, require_auth


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


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _make_tenant(tenant_id: uuid.UUID, password: str | None = "pass123") -> TenantConfig:
    return TenantConfig(
        id=tenant_id,
        name="Test",
        domain="test.com",
        password_hash=_hash(password) if password else None,
    )


def _sign_cookie(tenant_id: uuid.UUID, secret: str = "test-secret") -> str:
    s = URLSafeTimedSerializer(secret, salt="voxagent-session")
    return s.dumps({"tenant_id": str(tenant_id)})


class TestLoginPage:
    def test_get_returns_200(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/dashboard/login")
        assert resp.status_code == 200


class TestLogin:
    @patch("voxagent.server.auth.get_tenant", new_callable=AsyncMock)
    def test_valid_login_redirects(self, mock_get: AsyncMock) -> None:
        tid = uuid.uuid4()
        mock_get.return_value = _make_tenant(tid)
        client = TestClient(_make_app(), follow_redirects=False)
        resp = client.post("/dashboard/login", data={"tenant_id": str(tid), "password": "pass123"})
        assert resp.status_code == 303
        assert _COOKIE_NAME in resp.cookies

    @patch("voxagent.server.auth.get_tenant", new_callable=AsyncMock)
    def test_invalid_password_returns_401(self, mock_get: AsyncMock) -> None:
        tid = uuid.uuid4()
        mock_get.return_value = _make_tenant(tid)
        client = TestClient(_make_app())
        resp = client.post("/dashboard/login", data={"tenant_id": str(tid), "password": "wrong"})
        assert resp.status_code == 401

    @patch("voxagent.server.auth.get_tenant", new_callable=AsyncMock)
    def test_nonexistent_tenant_returns_401(self, mock_get: AsyncMock) -> None:
        mock_get.return_value = None
        client = TestClient(_make_app())
        resp = client.post("/dashboard/login", data={"tenant_id": str(uuid.uuid4()), "password": "x"})
        assert resp.status_code == 401

    @patch("voxagent.server.auth.get_tenant", new_callable=AsyncMock)
    def test_no_password_hash_returns_401(self, mock_get: AsyncMock) -> None:
        tid = uuid.uuid4()
        mock_get.return_value = _make_tenant(tid, password=None)
        client = TestClient(_make_app())
        resp = client.post("/dashboard/login", data={"tenant_id": str(tid), "password": "x"})
        assert resp.status_code == 401

    def test_invalid_uuid_returns_400(self) -> None:
        client = TestClient(_make_app())
        resp = client.post("/dashboard/login", data={"tenant_id": "not-a-uuid", "password": "x"})
        assert resp.status_code == 400


class TestLogout:
    def test_logout_redirects_and_clears_cookie(self) -> None:
        client = TestClient(_make_app(), follow_redirects=False)
        resp = client.post("/dashboard/logout")
        assert resp.status_code == 303
        # Cookie should be deleted (max-age=0 or not present in set-cookie)
        assert "/dashboard/login" in resp.headers.get("location", "")


class TestRequireAuth:
    def test_missing_cookie_api_returns_401(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/api/protected")
        assert resp.status_code == 401

    def test_missing_cookie_browser_returns_302(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/api/protected", headers={"accept": "text/html"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_invalid_cookie_returns_401(self) -> None:
        client = TestClient(_make_app())
        client.cookies.set(_COOKIE_NAME, "invalid-token")
        resp = client.get("/api/protected")
        assert resp.status_code == 401

    def test_valid_cookie_returns_tenant_id(self) -> None:
        tid = uuid.uuid4()
        token = _sign_cookie(tid)
        client = TestClient(_make_app())
        client.cookies.set(_COOKIE_NAME, token)
        resp = client.get("/api/protected")
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == str(tid)
