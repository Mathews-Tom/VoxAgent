from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from livekit.api import AccessToken, VideoGrants
from pydantic import BaseModel

from voxagent.metrics import TOKEN_ISSUANCE_TOTAL
from voxagent.queries import get_tenant

router = APIRouter()


class TokenRequest(BaseModel):
    tenant_id: str


class TokenResponse(BaseModel):
    token: str
    room_name: str
    livekit_url: str
    visitor_id: str


def _normalize_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if not parsed.scheme or not parsed.netloc:
        return origin.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def origin_allowed(origin: str | None, allowed_origins: list[str], allow_localhost: bool) -> bool:
    if origin is None:
        return False
    normalized = _normalize_origin(origin)
    if allow_localhost and normalized.startswith(("http://localhost", "http://127.0.0.1")):
        return True
    return normalized in {_normalize_origin(item) for item in allowed_origins}


async def ensure_widget_origin_allowed(request: Request, tenant_id: uuid.UUID) -> None:
    pool = request.app.state.pool
    tenant = await get_tenant(pool, tenant_id)
    if tenant is None or not tenant.is_active:
        raise HTTPException(status_code=404, detail="Tenant not found")
    origin = request.headers.get("origin")
    if not origin_allowed(
        origin=origin,
        allowed_origins=tenant.allowed_origins,
        allow_localhost=request.app.state.config.allow_localhost_widget_origins,
    ):
        raise HTTPException(status_code=403, detail="Origin not allowed")


@router.post("/api/token", response_model=TokenResponse)
async def create_token(body: TokenRequest, request: Request) -> TokenResponse:
    config = request.app.state.config
    pool = request.app.state.pool

    try:
        tenant_id = uuid.UUID(body.tenant_id)
    except ValueError as exc:
        TOKEN_ISSUANCE_TOTAL.labels(tenant_id="invalid", outcome="invalid_tenant_id").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID") from exc

    tenant = await get_tenant(pool, tenant_id)
    if tenant is None or not tenant.is_active:
        TOKEN_ISSUANCE_TOTAL.labels(tenant_id=str(tenant_id), outcome="tenant_not_found").inc()
        raise HTTPException(status_code=404, detail="Tenant not found")

    origin = request.headers.get("origin")
    if not origin_allowed(
        origin=origin,
        allowed_origins=tenant.allowed_origins,
        allow_localhost=config.allow_localhost_widget_origins,
    ):
        TOKEN_ISSUANCE_TOTAL.labels(tenant_id=str(tenant_id), outcome="origin_rejected").inc()
        raise HTTPException(status_code=403, detail="Origin not allowed")

    visitor_id = uuid.uuid4()
    room_name = f"{tenant_id}_{visitor_id}"

    token = AccessToken(api_key=config.livekit_api_key, api_secret=config.livekit_api_secret)
    token.identity = str(visitor_id)
    token.name = f"visitor-{visitor_id}"
    token.video_grants = VideoGrants(room_join=True, room=room_name)
    token.attributes = {
        "tenant_id": str(tenant_id),
        "widget_origin": _normalize_origin(origin),
        "session_type": "widget",
    }
    jwt_token = token.to_jwt()
    TOKEN_ISSUANCE_TOTAL.labels(tenant_id=str(tenant_id), outcome="issued").inc()

    return TokenResponse(
        token=jwt_token,
        room_name=room_name,
        livekit_url=config.livekit_url,
        visitor_id=str(visitor_id),
    )
