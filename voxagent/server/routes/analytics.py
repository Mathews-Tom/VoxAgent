from __future__ import annotations

import uuid
from pathlib import Path

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from voxagent.models import AuthContext
from voxagent.server.auth import require_auth_context

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/dashboard")


def _verify_tenant(auth_context: AuthContext, tenant_id: uuid.UUID) -> None:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")


async def _get_analytics(pool: asyncpg.Pool, tenant_id: uuid.UUID) -> dict[str, object]:  # noqa: C901
    total_conversations: int = await pool.fetchval(
        "SELECT COUNT(*) FROM conversations WHERE tenant_id = $1",
        tenant_id,
    )

    total_leads: int = await pool.fetchval(
        "SELECT COUNT(*) FROM leads WHERE tenant_id = $1",
        tenant_id,
    )

    avg_duration: float = await pool.fetchval(
        "SELECT COALESCE(AVG(duration_seconds), 0) FROM conversations WHERE tenant_id = $1",
        tenant_id,
    )

    by_language_rows = await pool.fetch(
        """
        SELECT language, COUNT(*) AS cnt
        FROM conversations
        WHERE tenant_id = $1
        GROUP BY language
        ORDER BY cnt DESC
        """,
        tenant_id,
    )
    by_language: dict[str, int] = {
        (r["language"] or "unknown"): r["cnt"] for r in by_language_rows
    }

    over_time_rows = await pool.fetch(
        """
        SELECT DATE(started_at) AS day, COUNT(*) AS cnt
        FROM conversations
        WHERE tenant_id = $1 AND started_at >= NOW() - INTERVAL '30 days'
        GROUP BY day
        ORDER BY day
        """,
        tenant_id,
    )
    over_time: list[dict[str, object]] = [
        {"day": str(r["day"]), "cnt": r["cnt"]} for r in over_time_rows
    ]

    top_intents_rows = await pool.fetch(
        """
        SELECT intent, COUNT(*) AS cnt
        FROM leads
        WHERE tenant_id = $1 AND intent IS NOT NULL
        GROUP BY intent
        ORDER BY cnt DESC
        LIMIT 10
        """,
        tenant_id,
    )
    top_intents: list[dict[str, object]] = [
        {"intent": r["intent"], "cnt": r["cnt"]} for r in top_intents_rows
    ]

    return {
        "total_conversations": total_conversations,
        "total_leads": total_leads,
        "avg_duration": float(avg_duration),
        "by_language": by_language,
        "over_time": over_time,
        "top_intents": top_intents,
    }


@router.get("/{tenant_id}/analytics", response_class=HTMLResponse)
async def analytics_page(
    tenant_id: uuid.UUID,
    request: Request,
    auth_context: AuthContext = Depends(require_auth_context),
) -> HTMLResponse:
    _verify_tenant(auth_context, tenant_id)

    pool = request.app.state.pool
    analytics = await _get_analytics(pool, tenant_id)

    avg_duration_raw: float = analytics["avg_duration"]  # type: ignore[assignment]
    avg_seconds = int(avg_duration_raw)
    avg_duration_formatted = f"{avg_seconds // 60}:{avg_seconds % 60:02d}"

    return templates.TemplateResponse(
        "analytics.html",
        {
            "request": request,
            "tenant_id": str(tenant_id),
            "active_page": "analytics",
            "total_conversations": analytics["total_conversations"],
            "total_leads": analytics["total_leads"],
            "avg_duration": avg_duration_formatted,
            "by_language": analytics["by_language"],
            "over_time": analytics["over_time"],
            "top_intents": analytics["top_intents"],
        },
    )
