from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from voxagent.queries import get_conversation, list_conversations
from voxagent.models import AuthContext
from voxagent.server.auth import require_auth_context

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/dashboard")


@router.get("/{tenant_id}/conversations", response_class=HTMLResponse)
async def conversations_page(
    tenant_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthContext = Depends(require_auth_context),
) -> HTMLResponse:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    pool = request.app.state.pool
    conversations = await list_conversations(pool, tenant_id, limit=limit, offset=offset)

    return templates.TemplateResponse(
        "conversations.html",
        {
            "request": request,
            "tenant_id": str(tenant_id),
            "conversations": conversations,
            "limit": limit,
            "offset": offset,
            "active_page": "conversations",
        },
    )


@router.get("/{tenant_id}/conversations/{conversation_id}", response_class=HTMLResponse)
async def conversation_detail(
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: Request,
    auth_context: AuthContext = Depends(require_auth_context),
) -> HTMLResponse:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    pool = request.app.state.pool
    conversation = await get_conversation(pool, conversation_id)

    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conversation.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return templates.TemplateResponse(
        "conversation_detail.html",
        {
            "request": request,
            "conversation": conversation,
        },
    )
