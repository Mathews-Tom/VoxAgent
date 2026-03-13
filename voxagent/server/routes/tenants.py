from __future__ import annotations

import uuid
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from voxagent.models import (
    AdminRole,
    AdminUser,
    AuthContext,
    ConfigAuditLogEntry,
    LLMConfig,
    MCPServerConfig,
    STTConfig,
    TTSConfig,
    TenantConfig,
)
from voxagent.queries import (
    create_config_audit_log,
    create_tenant_with_admin,
    delete_tenant,
    get_tenant,
    list_tenants,
    update_tenant,
)
from voxagent.server.auth import hash_password, require_auth_context, require_platform_admin
from voxagent.server.routes.widget import ensure_widget_origin_allowed

router = APIRouter(tags=["tenants"])

_MASK = "********"


class PublicCreateTenantRequest(BaseModel):
    name: str
    domain: str
    admin_email: str
    password: str = Field(min_length=8)
    stt: STTConfig | None = None
    llm: LLMConfig | None = None
    tts: TTSConfig | None = None
    greeting: str = "Hello! How can I help you today?"
    widget_color: str = "#6366f1"
    widget_position: str = "bottom-right"
    allowed_origins: list[str] = Field(default_factory=list)


class UpdateTenantRequest(BaseModel):
    name: str | None = None
    domain: str | None = None
    is_active: bool | None = None
    stt: STTConfig | None = None
    llm: LLMConfig | None = None
    tts: TTSConfig | None = None
    greeting: str | None = None
    widget_color: str | None = None
    widget_position: str | None = None
    allowed_origins: list[str] | None = None
    webhook_url: str | None = None
    mcp_servers: list[MCPServerConfig] | None = None


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    domain: str
    is_active: bool
    stt: STTConfig
    llm: LLMConfig
    tts: TTSConfig
    greeting: str
    widget_color: str
    widget_position: str
    allowed_origins: list[str]
    webhook_url: str | None
    mcp_servers: list[MCPServerConfig]
    created_at: datetime


class TenantConfigResponse(BaseModel):
    greeting: str
    widget_color: str
    widget_position: str


def _mask_secret(value: str | None) -> str | None:
    if value is None:
        return None
    return _MASK


def _mask_webhook_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    masked = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    return masked or _MASK


def _tenant_to_response(tenant: TenantConfig) -> TenantResponse:
    masked_servers = [
        MCPServerConfig(
            name=server.name,
            url=server.url,
            api_key=_mask_secret(server.api_key),
        )
        for server in tenant.mcp_servers
    ]
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        domain=tenant.domain,
        is_active=tenant.is_active,
        stt=tenant.stt,
        llm=tenant.llm,
        tts=tenant.tts,
        greeting=tenant.greeting,
        widget_color=tenant.widget_color,
        widget_position=tenant.widget_position,
        allowed_origins=tenant.allowed_origins,
        webhook_url=_mask_webhook_url(tenant.webhook_url),
        mcp_servers=masked_servers,
        created_at=tenant.created_at,
    )


def _ensure_tenant_access(auth_context: AuthContext, tenant_id: uuid.UUID) -> None:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")


async def _audit(
    request: Request,
    auth_context: AuthContext,
    action: str,
    tenant_id: uuid.UUID | None,
    diff_summary: str,
) -> None:
    await create_config_audit_log(
        request.app.state.pool,
        ConfigAuditLogEntry(
            actor_admin_user_id=auth_context.admin_user_id,
            tenant_id=tenant_id,
            action=action,
            diff_summary=diff_summary,
        ),
    )


@router.post(
    "/api/public/tenants",
    status_code=status.HTTP_201_CREATED,
    response_model=TenantResponse,
)
async def create_public_tenant_route(
    body: PublicCreateTenantRequest,
    request: Request,
) -> TenantResponse:
    pool = request.app.state.pool
    tenant = TenantConfig(
        name=body.name,
        domain=body.domain,
        stt=body.stt if body.stt is not None else STTConfig(),
        llm=body.llm if body.llm is not None else LLMConfig(),
        tts=body.tts if body.tts is not None else TTSConfig(),
        greeting=body.greeting,
        widget_color=body.widget_color,
        widget_position=body.widget_position,
        allowed_origins=body.allowed_origins,
    )
    admin_user = AdminUser(
        email=body.admin_email,
        password_hash=hash_password(body.password),
    )
    created, _, _ = await create_tenant_with_admin(pool, tenant, admin_user)
    return _tenant_to_response(created)


@router.get("/api/tenants", response_model=list[TenantResponse])
async def list_tenants_route(
    request: Request,
    _: AuthContext = Depends(require_platform_admin),
) -> list[TenantResponse]:
    pool = request.app.state.pool
    tenants = await list_tenants(pool)
    return [_tenant_to_response(t) for t in tenants]


@router.get("/api/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant_route(
    tenant_id: uuid.UUID,
    request: Request,
    auth_context: AuthContext = Depends(require_auth_context),
) -> TenantResponse:
    _ensure_tenant_access(auth_context, tenant_id)
    pool = request.app.state.pool
    tenant = await get_tenant(pool, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id} not found")
    return _tenant_to_response(tenant)


async def _update_tenant(
    tenant_id: uuid.UUID,
    body: UpdateTenantRequest,
    request: Request,
    auth_context: AuthContext = Depends(require_auth_context),
) -> TenantResponse:
    _ensure_tenant_access(auth_context, tenant_id)
    pool = request.app.state.pool
    existing = await get_tenant(pool, tenant_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id} not found")
    updated = TenantConfig(
        id=existing.id,
        name=body.name if body.name is not None else existing.name,
        domain=body.domain if body.domain is not None else existing.domain,
        is_active=body.is_active if body.is_active is not None else existing.is_active,
        password_hash=existing.password_hash,
        stt=body.stt if body.stt is not None else existing.stt,
        llm=body.llm if body.llm is not None else existing.llm,
        tts=body.tts if body.tts is not None else existing.tts,
        greeting=body.greeting if body.greeting is not None else existing.greeting,
        widget_color=body.widget_color if body.widget_color is not None else existing.widget_color,
        widget_position=body.widget_position if body.widget_position is not None else existing.widget_position,
        allowed_origins=body.allowed_origins if body.allowed_origins is not None else existing.allowed_origins,
        webhook_url=body.webhook_url if body.webhook_url is not None else existing.webhook_url,
        mcp_servers=body.mcp_servers if body.mcp_servers is not None else existing.mcp_servers,
        created_at=existing.created_at,
    )
    result = await update_tenant(pool, updated)
    await _audit(
        request=request,
        auth_context=auth_context,
        action="tenant.update",
        tenant_id=tenant_id,
        diff_summary="Updated tenant configuration",
    )
    return _tenant_to_response(result)


@router.put("/api/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant_route(
    tenant_id: uuid.UUID,
    body: UpdateTenantRequest,
    request: Request,
    auth_context: AuthContext = Depends(require_auth_context),
) -> TenantResponse:
    return await _update_tenant(tenant_id, body, request, auth_context)


@router.post("/api/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant_route_from_form(
    tenant_id: uuid.UUID,
    body: UpdateTenantRequest,
    request: Request,
    auth_context: AuthContext = Depends(require_auth_context),
) -> TenantResponse:
    return await _update_tenant(tenant_id, body, request, auth_context)


@router.delete("/api/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_route(
    tenant_id: uuid.UUID,
    request: Request,
    auth_context: AuthContext = Depends(require_platform_admin),
) -> None:
    pool = request.app.state.pool
    existing = await get_tenant(pool, tenant_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id} not found")
    await delete_tenant(pool, tenant_id)
    await _audit(
        request=request,
        auth_context=auth_context,
        action="tenant.delete",
        tenant_id=tenant_id,
        diff_summary=f"Deleted tenant {tenant_id}",
    )


@router.get("/api/tenants/{tenant_id}/config", response_model=TenantConfigResponse)
async def get_tenant_config_route(tenant_id: uuid.UUID, request: Request) -> TenantConfigResponse:
    await ensure_widget_origin_allowed(request, tenant_id)
    pool = request.app.state.pool
    tenant = await get_tenant(pool, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id} not found")
    return TenantConfigResponse(
        greeting=tenant.greeting,
        widget_color=tenant.widget_color,
        widget_position=tenant.widget_position,
    )
