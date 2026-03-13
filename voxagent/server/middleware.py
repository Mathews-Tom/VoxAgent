from __future__ import annotations

import os
import json
import re
import time
import uuid
from dataclasses import dataclass
from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send
from voxagent.metrics import RATE_LIMIT_DECISIONS
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


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    limit: int
    window_seconds: int
    fail_open: bool


class InMemoryRateLimitStore:
    def __init__(self) -> None:
        self._limiters: dict[str, RateLimiter] = {}

    async def is_allowed(self, policy: RateLimitPolicy, key: str) -> bool:
        limiter = self._limiters.get(policy.name)
        if limiter is None:
            limiter = RateLimiter(limit=policy.limit, window_seconds=policy.window_seconds)
            self._limiters[policy.name] = limiter
        return limiter.is_allowed(key)


class RedisRateLimitStore:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: object | None = None

    async def is_allowed(self, policy: RateLimitPolicy, key: str) -> bool:
        redis = await self._get_client()
        counter_key = f"voxagent:rate-limit:{policy.name}:{key}"
        count = await redis.incr(counter_key)
        if count == 1:
            await redis.expire(counter_key, policy.window_seconds)
        return int(count) <= policy.limit

    async def _get_client(self) -> object:
        if self._client is not None:
            return self._client

        try:
            from redis import asyncio as redis_asyncio
        except ImportError as exc:
            raise RuntimeError("Redis rate limit backend requested but redis package is unavailable") from exc

        self._client = redis_asyncio.from_url(self._redis_url, encoding="utf-8", decode_responses=True)
        return self._client


def build_rate_limit_store() -> InMemoryRateLimitStore | RedisRateLimitStore:
    backend = os.environ.get("RATE_LIMIT_BACKEND", "memory").lower()
    redis_url = os.environ.get("RATE_LIMIT_REDIS_URL")
    if backend == "redis" and redis_url:
        return RedisRateLimitStore(redis_url)
    return InMemoryRateLimitStore()


_RATE_LIMIT_POLICIES = {
    "public": RateLimitPolicy(name="public", limit=30, window_seconds=60, fail_open=True),
    "auth": RateLimitPolicy(name="auth", limit=10, window_seconds=60, fail_open=False),
    "admin": RateLimitPolicy(name="admin", limit=120, window_seconds=60, fail_open=False),
}


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        store: InMemoryRateLimitStore | RedisRateLimitStore | None = None,
    ) -> None:
        self._app = app
        self._store = store or build_rate_limit_store()

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
        policy_name = _classify_path(path)
        policy = _RATE_LIMIT_POLICIES[policy_name]
        tenant_key = _extract_tenant_key(path)
        key = f"{tenant_key or ip}"

        request_token = request_id_var.set(headers.get("x-request-id", str(uuid.uuid4())))
        tenant_token = tenant_id_var.set(tenant_key)
        try:
            try:
                allowed = await self._store.is_allowed(policy, key)
            except Exception:
                RATE_LIMIT_DECISIONS.labels(policy=policy.name, outcome="backend_error").inc()
                if not policy.fail_open:
                    await self._send_503(send)
                    return
                allowed = True

            if not allowed:
                RATE_LIMIT_DECISIONS.labels(policy=policy.name, outcome="blocked").inc()
                await self._send_429(send)
                return

            RATE_LIMIT_DECISIONS.labels(policy=policy.name, outcome="allowed").inc()
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

    @staticmethod
    async def _send_503(send: Send) -> None:
        body = json.dumps({"detail": "Rate limit backend unavailable"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
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
