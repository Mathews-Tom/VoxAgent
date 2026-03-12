from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from voxagent.models import TenantConfig
from voxagent.queries import get_tenant, list_leads, update_tenant
from voxagent.server.auth import require_auth

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/dashboard")


def _verify_tenant(auth_tenant_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    if auth_tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/{tenant_id}/leads", response_class=HTMLResponse)
async def leads_page(
    tenant_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    auth_tenant_id: uuid.UUID = Depends(require_auth),
) -> HTMLResponse:
    _verify_tenant(auth_tenant_id, tenant_id)

    pool = request.app.state.pool
    leads = await list_leads(pool, tenant_id, limit=limit, offset=offset)

    return templates.TemplateResponse(
        "leads.html",
        {
            "request": request,
            "tenant_id": str(tenant_id),
            "leads": leads,
            "limit": limit,
            "offset": offset,
            "active_page": "leads",
        },
    )


@router.get("/{tenant_id}/voice-config", response_class=HTMLResponse)
async def voice_config_page(
    tenant_id: uuid.UUID,
    request: Request,
    auth_tenant_id: uuid.UUID = Depends(require_auth),
) -> HTMLResponse:
    _verify_tenant(auth_tenant_id, tenant_id)

    pool = request.app.state.pool
    tenant = await get_tenant(pool, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return templates.TemplateResponse(
        "voice_config.html",
        {
            "request": request,
            "tenant_id": str(tenant_id),
            "tenant": tenant,
            "active_page": "voice_config",
        },
    )


@router.get("/{tenant_id}/widget-config", response_class=HTMLResponse)
async def widget_config_page(
    tenant_id: uuid.UUID,
    request: Request,
    auth_tenant_id: uuid.UUID = Depends(require_auth),
) -> HTMLResponse:
    _verify_tenant(auth_tenant_id, tenant_id)

    pool = request.app.state.pool
    tenant = await get_tenant(pool, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return templates.TemplateResponse(
        "widget_config.html",
        {
            "request": request,
            "tenant_id": str(tenant_id),
            "tenant": tenant,
            "active_page": "widget_config",
        },
    )


@router.post("/{tenant_id}/widget-config", response_class=HTMLResponse)
async def widget_config_save(
    tenant_id: uuid.UUID,
    request: Request,
    widget_color: str = Form(...),
    greeting: str = Form(...),
    widget_position: str = Form(...),
    auth_tenant_id: uuid.UUID = Depends(require_auth),
) -> HTMLResponse:
    _verify_tenant(auth_tenant_id, tenant_id)

    pool = request.app.state.pool
    tenant = await get_tenant(pool, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Collect allowed_origins from form (multiple inputs with same name)
    form_data = await request.form()
    allowed_origins = [
        v for v in form_data.getlist("allowed_origins") if isinstance(v, str) and v.strip()
    ]

    updated = TenantConfig(
        id=tenant.id,
        name=tenant.name,
        domain=tenant.domain,
        password_hash=tenant.password_hash,
        stt=tenant.stt,
        llm=tenant.llm,
        tts=tenant.tts,
        greeting=greeting,
        widget_color=widget_color,
        widget_position=widget_position,
        allowed_origins=allowed_origins,
        webhook_url=tenant.webhook_url,
        mcp_servers=tenant.mcp_servers,
        created_at=tenant.created_at,
    )
    result = await update_tenant(pool, updated)

    return templates.TemplateResponse(
        "widget_config.html",
        {
            "request": request,
            "tenant_id": str(tenant_id),
            "tenant": result,
            "active_page": "widget_config",
            "save_success": True,
        },
    )


@router.get("/{tenant_id}/webhooks", response_class=HTMLResponse)
async def webhooks_page(
    tenant_id: uuid.UUID,
    request: Request,
    auth_tenant_id: uuid.UUID = Depends(require_auth),
) -> HTMLResponse:
    _verify_tenant(auth_tenant_id, tenant_id)

    pool = request.app.state.pool
    tenant = await get_tenant(pool, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return templates.TemplateResponse(
        "webhooks.html",
        {
            "request": request,
            "tenant_id": str(tenant_id),
            "webhook_url": tenant.webhook_url,
            "active_page": "webhooks",
        },
    )


@router.post("/{tenant_id}/webhooks", response_class=HTMLResponse)
async def webhooks_save(
    tenant_id: uuid.UUID,
    request: Request,
    webhook_url: str = Form(default=""),
    auth_tenant_id: uuid.UUID = Depends(require_auth),
) -> HTMLResponse:
    _verify_tenant(auth_tenant_id, tenant_id)

    pool = request.app.state.pool
    tenant = await get_tenant(pool, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    updated = TenantConfig(
        id=tenant.id,
        name=tenant.name,
        domain=tenant.domain,
        password_hash=tenant.password_hash,
        stt=tenant.stt,
        llm=tenant.llm,
        tts=tenant.tts,
        greeting=tenant.greeting,
        widget_color=tenant.widget_color,
        widget_position=tenant.widget_position,
        allowed_origins=tenant.allowed_origins,
        webhook_url=webhook_url.strip() or None,
        mcp_servers=tenant.mcp_servers,
        created_at=tenant.created_at,
    )
    result = await update_tenant(pool, updated)

    return templates.TemplateResponse(
        "webhooks.html",
        {
            "request": request,
            "tenant_id": str(tenant_id),
            "webhook_url": result.webhook_url,
            "active_page": "webhooks",
            "save_success": True,
        },
    )
