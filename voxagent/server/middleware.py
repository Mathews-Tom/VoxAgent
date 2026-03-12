from __future__ import annotations

import json
import re
import time

from starlette.types import ASGIApp, Receive, Scope, Send

_UUID_RE = re.compile(
    r"^/api/tenants/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/"
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

        # Evict expired timestamps in place
        valid_start = 0
        for i, ts in enumerate(timestamps):
            if ts >= cutoff:
                valid_start = i
                break
        else:
            # All timestamps are expired if the loop didn't break
            valid_start = len(timestamps)

        timestamps[:] = timestamps[valid_start:]

        if len(timestamps) >= self._limit:
            return False

        timestamps.append(now)
        return True


class RateLimitMiddleware:
    """ASGI middleware for rate limiting."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._ip_limiter = RateLimiter(limit=30, window_seconds=60)
        self._tenant_limiter = RateLimiter(limit=100, window_seconds=60)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        client = scope.get("client")
        ip: str = client[0] if client else "unknown"

        if not self._ip_limiter.is_allowed(ip):
            await self._send_429(send)
            return

        path: str = scope.get("path", "")
        match = _UUID_RE.match(path)
        if match:
            tenant_id = match.group(1)
            if not self._tenant_limiter.is_allowed(tenant_id):
                await self._send_429(send)
                return

        await self._app(scope, receive, send)

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
