from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from voxagent.server.middleware import RateLimitMiddleware


def _http_scope(path: str = "/", client: tuple[str, int] = ("127.0.0.1", 9000)) -> dict:
    return {
        "type": "http",
        "path": path,
        "client": client,
        "method": "GET",
    }


def _non_http_scope() -> dict:
    return {"type": "websocket", "path": "/ws"}


class TestRateLimitMiddleware:
    @pytest.mark.asyncio
    async def test_passes_non_http_scope(self) -> None:
        app = AsyncMock()
        mw = RateLimitMiddleware(app)
        scope = _non_http_scope()
        receive = AsyncMock()
        send = AsyncMock()
        await mw(scope, receive, send)
        app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_allows_under_ip_limit(self) -> None:
        app = AsyncMock()
        mw = RateLimitMiddleware(app)
        receive = AsyncMock()
        send = AsyncMock()
        for _ in range(5):
            await mw(_http_scope(), receive, send)
        assert app.call_count == 5

    @pytest.mark.asyncio
    async def test_blocks_ip_over_limit(self) -> None:
        app = AsyncMock()
        mw = RateLimitMiddleware(app)
        receive = AsyncMock()
        send = AsyncMock()
        # Default IP limit is 120
        for _ in range(120):
            await mw(_http_scope(), receive, send)
        assert app.call_count == 120

        # 121st request should be blocked
        send_31 = AsyncMock()
        await mw(_http_scope(), receive, send_31)
        assert app.call_count == 120  # unchanged
        # Check 429 was sent
        start_call = send_31.call_args_list[0][0][0]
        assert start_call["status"] == 429

    @pytest.mark.asyncio
    async def test_tenant_rate_limiting(self) -> None:
        app = AsyncMock()
        mw = RateLimitMiddleware(app)
        receive = AsyncMock()
        tid = uuid.uuid4()
        path = f"/api/tenants/{tid}/leads"
        # Admin-class endpoints are limited to 120/minute.
        for i in range(120):
            scope = _http_scope(path=path, client=(f"10.{i // 256}.{i % 256}.1", 9000))
            await mw(scope, receive, AsyncMock())
        assert app.call_count == 120

        # 121st request with new IP but same tenant
        send_101 = AsyncMock()
        scope = _http_scope(path=path, client=("192.168.1.1", 9000))
        await mw(scope, receive, send_101)
        assert app.call_count == 120
        start_call = send_101.call_args_list[0][0][0]
        assert start_call["status"] == 429

    @pytest.mark.asyncio
    async def test_different_ips_independent(self) -> None:
        app = AsyncMock()
        mw = RateLimitMiddleware(app)
        receive = AsyncMock()
        # Fill up limit for IP A
        for _ in range(120):
            await mw(_http_scope(client=("1.1.1.1", 9000)), receive, AsyncMock())
        # IP B should still work
        send_b = AsyncMock()
        await mw(_http_scope(client=("2.2.2.2", 9000)), receive, send_b)
        # app was called 121 times total (120 for A + 1 for B)
        assert app.call_count == 121

    @pytest.mark.asyncio
    async def test_non_tenant_path_skips_tenant_limiting(self) -> None:
        app = AsyncMock()
        mw = RateLimitMiddleware(app)
        receive = AsyncMock()
        # Non-tenant path shouldn't trigger tenant limiter
        for i in range(5):
            scope = _http_scope(path="/api/health", client=(f"10.0.{i}.1", 9000))
            await mw(scope, receive, AsyncMock())
        assert app.call_count == 5

    @pytest.mark.asyncio
    async def test_429_body_is_correct_json(self) -> None:
        app = AsyncMock()
        mw = RateLimitMiddleware(app)
        receive = AsyncMock()
        # Exceed IP limit
        for _ in range(120):
            await mw(_http_scope(), receive, AsyncMock())

        send = AsyncMock()
        await mw(_http_scope(), receive, send)
        body_call = send.call_args_list[1][0][0]
        parsed = json.loads(body_call["body"])
        assert parsed == {"detail": "Rate limit exceeded"}

    @pytest.mark.asyncio
    async def test_public_policy_fails_open_when_backend_errors(self) -> None:
        app = AsyncMock()

        class _BrokenStore:
            async def is_allowed(self, policy: object, key: str) -> bool:
                raise RuntimeError("redis unavailable")

        mw = RateLimitMiddleware(app, store=_BrokenStore())
        receive = AsyncMock()
        send = AsyncMock()

        await mw(_http_scope(path="/api/token"), receive, send)

        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_policy_fails_closed_when_backend_errors(self) -> None:
        app = AsyncMock()

        class _BrokenStore:
            async def is_allowed(self, policy: object, key: str) -> bool:
                raise RuntimeError("redis unavailable")

        mw = RateLimitMiddleware(app, store=_BrokenStore())
        receive = AsyncMock()
        send = AsyncMock()

        await mw(_http_scope(path="/api/tenants"), receive, send)

        app.assert_not_called()
        start_call = send.call_args_list[0][0][0]
        assert start_call["status"] == 503
