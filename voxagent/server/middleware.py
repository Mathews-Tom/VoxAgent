from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send
from voxagent.logging_config import request_id_var, tenant_id_var

_TENANT_PATH_RE = re.compile(
    r"^/api/tenants/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)

_429_BODY = json.dumps({"detail": "Rate limit exceeded"}).encode()
_429_HEADERS = [
    (b"content-type", b"application/json"),
    (b"content-length", str(len(_429_BODY)).encode()),
]


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self._limit = limit
        self._window = window_seconds
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        timestamps = self._requests.get(key)
        if timestamps is None:
            self._requests[key] = [now]
            return True

        timestamps[:] = [timestamp for timestamp in timestamps if timestamp >= cutoff]
        if len(timestamps) >= self._limit:
            return False

        timestamps.append(now)
        return True


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._limiters = {
            "public": RateLimiter(limit=30, window_seconds=60),
            "auth": RateLimiter(limit=10, window_seconds=60),
            "admin": RateLimiter(limit=120, window_seconds=60),
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET")).upper()
        headers = {key.decode(): value.decode() for key, value in scope.get("headers", [])}
        origin = headers.get("origin")

        if method == "OPTIONS" and _is_public_edge_path(path):
            await _send_cors_preflight(send, origin, headers.get("access-control-request-headers", "content-type"))
            return

        client = scope.get("client")
        ip = client[0] if client else "unknown"
        policy = _classify_path(path)
        tenant_key = _extract_tenant_key(path)
        key = f"{policy}:{tenant_key or ip}"

        if not self._limiters[policy].is_allowed(key):
            await self._send_429(send)
            return

        request_token = request_id_var.set(headers.get("x-request-id", str(uuid.uuid4())))
        tenant_token = tenant_id_var.set(tenant_key)
        try:
            if not origin or not _is_public_edge_path(path):
                await self._app(scope, receive, send)
                return

            async def send_with_cors(message: Message) -> None:
                if message["type"] == "http.response.start":
                    headers_list = list(message.get("headers", []))
                    headers_list.extend(_cors_headers(origin))
                    headers_list.append((b"x-request-id", request_id_var.get().encode()))
                    message["headers"] = headers_list
                await send(message)

            await self._app(scope, receive, send_with_cors)
        finally:
            request_id_var.reset(request_token)
            tenant_id_var.reset(tenant_token)

    @staticmethod
    async def _send_429(send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": _429_HEADERS,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": _429_BODY,
                "more_body": False,
            }
        )


def _classify_path(path: str) -> str:
    if path == "/api/token" or path.endswith("/config"):
        return "public"
    if path.startswith("/dashboard/login") or path.startswith("/dashboard/logout"):
        return "auth"
    return "admin"


def _extract_tenant_key(path: str) -> str | None:
    if path == "/api/token":
        return None
    match = _TENANT_PATH_RE.match(path)
    if match:
        return match.group(1)
    return None


def _is_public_edge_path(path: str) -> bool:
    return path == "/api/token" or path.endswith("/config")


def _cors_headers(origin: str) -> list[tuple[bytes, bytes]]:
    return [
        (b"access-control-allow-origin", origin.encode()),
        (b"access-control-allow-credentials", b"true"),
        (b"access-control-allow-methods", b"GET,POST,OPTIONS"),
        (b"vary", b"Origin"),
    ]


async def _send_cors_preflight(send: Send, origin: str | None, request_headers: str) -> None:
    headers = list(_cors_headers(origin or "null"))
    headers.append((b"access-control-allow-headers", request_headers.encode()))
    await send(
        {
            "type": "http.response.start",
            "status": 204,
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": b"", "more_body": False})
