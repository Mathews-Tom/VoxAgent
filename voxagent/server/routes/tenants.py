from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from voxagent.models import LLMConfig, MCPServerConfig, STTConfig, TTSConfig, TenantConfig
from voxagent.queries import (
    create_tenant,
    delete_tenant,
    get_tenant,
    list_tenants,
    update_tenant,
)

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


class CreateTenantRequest(BaseModel):
    name: str
    domain: str
    password: str | None = None
    stt: STTConfig | None = None
    llm: LLMConfig | None = None
    tts: TTSConfig | None = None
    greeting: str = "Hello! How can I help you today?"
    widget_color: str = "#6366f1"
    widget_position: str = "bottom-right"
    allowed_origins: list[str] = []
    webhook_url: str | None = None
    mcp_servers: list[MCPServerConfig] = []


class UpdateTenantRequest(BaseModel):
    name: str | None = None
    domain: str | None = None
    password: str | None = None
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


def _tenant_to_response(tenant: TenantConfig) -> TenantResponse:
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        domain=tenant.domain,
        stt=tenant.stt,
        llm=tenant.llm,
        tts=tenant.tts,
        greeting=tenant.greeting,
        widget_color=tenant.widget_color,
        widget_position=tenant.widget_position,
        allowed_origins=tenant.allowed_origins,
        webhook_url=tenant.webhook_url,
        mcp_servers=tenant.mcp_servers,
        created_at=tenant.created_at,
    )


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TenantResponse)
async def create_tenant_route(body: CreateTenantRequest, request: Request) -> TenantResponse:
    pool = request.app.state.pool
    tenant = TenantConfig(
        name=body.name,
        domain=body.domain,
        password_hash=_hash_password(body.password) if body.password is not None else None,
        stt=body.stt if body.stt is not None else STTConfig(),
        llm=body.llm if body.llm is not None else LLMConfig(),
        tts=body.tts if body.tts is not None else TTSConfig(),
        greeting=body.greeting,
        widget_color=body.widget_color,
        widget_position=body.widget_position,
        allowed_origins=body.allowed_origins,
        webhook_url=body.webhook_url,
        mcp_servers=body.mcp_servers,
    )
    created = await create_tenant(pool, tenant)
    return _tenant_to_response(created)


@router.get("", response_model=list[TenantResponse])
async def list_tenants_route(request: Request) -> list[TenantResponse]:
    pool = request.app.state.pool
    tenants = await list_tenants(pool)
    return [_tenant_to_response(t) for t in tenants]


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant_route(tenant_id: uuid.UUID, request: Request) -> TenantResponse:
    pool = request.app.state.pool
    tenant = await get_tenant(pool, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id} not found")
    return _tenant_to_response(tenant)


@router.put("/{tenant_id}", response_model=TenantResponse)
async def update_tenant_route(
    tenant_id: uuid.UUID, body: UpdateTenantRequest, request: Request
) -> TenantResponse:
    pool = request.app.state.pool
    existing = await get_tenant(pool, tenant_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id} not found")
    updated = TenantConfig(
        id=existing.id,
        name=body.name if body.name is not None else existing.name,
        domain=body.domain if body.domain is not None else existing.domain,
        password_hash=_hash_password(body.password) if body.password is not None else existing.password_hash,
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
    return _tenant_to_response(result)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_route(tenant_id: uuid.UUID, request: Request) -> None:
    pool = request.app.state.pool
    existing = await get_tenant(pool, tenant_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id} not found")
    await delete_tenant(pool, tenant_id)


@router.get("/{tenant_id}/config", response_model=TenantConfigResponse)
async def get_tenant_config_route(tenant_id: uuid.UUID, request: Request) -> TenantConfigResponse:
    pool = request.app.state.pool
    tenant = await get_tenant(pool, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id} not found")
    return TenantConfigResponse(
        greeting=tenant.greeting,
        widget_color=tenant.widget_color,
        widget_position=tenant.widget_position,
    )
