from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from voxagent.models import AuthContext, LeadRecord
from voxagent.queries import list_leads
from voxagent.server.auth import require_auth_context

router = APIRouter()

_CSV_FIELDS = ("id", "tenant_id", "conversation_id", "name", "email", "phone", "intent", "summary", "extracted_at")


@router.get("/api/tenants/{tenant_id}/leads", response_model=list[LeadRecord])
async def get_leads(
    tenant_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthContext = Depends(require_auth_context),
) -> list[LeadRecord]:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    pool = request.app.state.pool
    return await list_leads(pool, tenant_id, limit=limit, offset=offset)


@router.get("/api/tenants/{tenant_id}/leads/export")
async def export_leads(
    tenant_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthContext = Depends(require_auth_context),
) -> StreamingResponse:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    pool = request.app.state.pool
    leads = await list_leads(pool, tenant_id, limit=limit, offset=offset)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for lead in leads:
        writer.writerow({
            "id": str(lead.id),
            "tenant_id": str(lead.tenant_id),
            "conversation_id": str(lead.conversation_id),
            "name": lead.name or "",
            "email": lead.email or "",
            "phone": lead.phone or "",
            "intent": lead.intent or "",
            "summary": lead.summary or "",
            "extracted_at": lead.extracted_at.isoformat(),
        })

    buf.seek(0)
    filename = f"leads_{tenant_id}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
