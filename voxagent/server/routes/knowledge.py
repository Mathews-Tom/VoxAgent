from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from voxagent.knowledge.ingest import crawl_website, ingest_files
from voxagent.knowledge.service import (
    deactivate_source,
    knowledge_storage_dir,
    list_sources,
    orchestrate_ingestion,
    request_rebuild,
)
from voxagent.models import AuthContext
from voxagent.server.auth import require_auth_context

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/dashboard")

_SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}


def _knowledge_dir(tenant_id: uuid.UUID) -> Path:
    return knowledge_storage_dir(tenant_id)


def _load_sources(knowledge_dir: Path) -> list[dict[str, object]]:
    raise RuntimeError("Use list_sources() with a database pool instead of _load_sources().")


@router.get("/{tenant_id}/knowledge", response_class=HTMLResponse)
async def knowledge_page(
    tenant_id: uuid.UUID,
    request: Request,
    auth_context: AuthContext = Depends(require_auth_context),
) -> HTMLResponse:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    sources = await list_sources(request.app.state.pool, tenant_id)

    return templates.TemplateResponse(
        request,
        "knowledge.html",
        {
            "tenant_id": str(tenant_id),
            "sources": sources,
            "active_page": "knowledge",
        },
    )


@router.post("/{tenant_id}/knowledge/upload", response_class=HTMLResponse)
async def knowledge_upload(
    tenant_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    auth_context: AuthContext = Depends(require_auth_context),
) -> HTMLResponse:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()

    if suffix not in _SUPPORTED_EXTENSIONS:
        sources = await list_sources(request.app.state.pool, tenant_id)
        return templates.TemplateResponse(
            request,
            "knowledge.html",
            {
                "tenant_id": str(tenant_id),
                "sources": sources,
                "active_page": "knowledge",
                "upload_error": f"Unsupported file type '{suffix}'. Allowed: .txt, .pdf, .docx",
            },
        )

    contents = await file.read()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        pages = ingest_files([str(tmp_path)])
    finally:
        tmp_path.unlink(missing_ok=True)

    result = await orchestrate_ingestion(
        request.app.state.pool,
        tenant_id,
        pages,
        trigger="dashboard_upload",
    )

    sources = await list_sources(request.app.state.pool, tenant_id)
    return templates.TemplateResponse(
        request,
        "knowledge.html",
        {
            "tenant_id": str(tenant_id),
            "sources": sources,
            "active_page": "knowledge",
            "upload_queued": bool(result["queued"]),
            "upload_noop": not result["queued"],
        },
    )


@router.post("/{tenant_id}/knowledge/crawl", response_class=HTMLResponse)
async def knowledge_crawl(
    tenant_id: uuid.UUID,
    request: Request,
    url: str = Form(...),
    auth_context: AuthContext = Depends(require_auth_context),
) -> HTMLResponse:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    pages = await crawl_website(url)

    if not pages:
        sources = await list_sources(request.app.state.pool, tenant_id)
        return templates.TemplateResponse(
            request,
            "knowledge.html",
            {
                "tenant_id": str(tenant_id),
                "sources": sources,
                "active_page": "knowledge",
                "crawl_error": f"No pages could be retrieved from '{url}'.",
            },
        )

    result = await orchestrate_ingestion(
        request.app.state.pool,
        tenant_id,
        pages,
        trigger="dashboard_crawl",
    )

    sources = await list_sources(request.app.state.pool, tenant_id)
    return templates.TemplateResponse(
        request,
        "knowledge.html",
        {
            "tenant_id": str(tenant_id),
            "sources": sources,
            "active_page": "knowledge",
            "crawl_queued": bool(result["queued"]),
            "crawl_noop": not result["queued"],
        },
    )


@router.post("/{tenant_id}/knowledge/reindex", response_class=HTMLResponse)
async def knowledge_reindex(
    tenant_id: uuid.UUID,
    request: Request,
    auth_context: AuthContext = Depends(require_auth_context),
) -> HTMLResponse:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    await request_rebuild(
        request.app.state.pool,
        tenant_id,
        trigger="dashboard_reindex",
        changed_sources=[{"source_key": "all", "content_hash": "all"}],
        force=True,
    )
    sources = await list_sources(request.app.state.pool, tenant_id)
    return templates.TemplateResponse(
        request,
        "knowledge.html",
        {
            "tenant_id": str(tenant_id),
            "sources": sources,
            "active_page": "knowledge",
            "reindex_queued": True,
        },
    )


@router.post("/{tenant_id}/knowledge/recrawl", response_class=HTMLResponse)
async def knowledge_recrawl(
    tenant_id: uuid.UUID,
    request: Request,
    source: str = Form(...),
    auth_context: AuthContext = Depends(require_auth_context),
) -> HTMLResponse:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    pages = await crawl_website(source)
    if not pages:
        sources = await list_sources(request.app.state.pool, tenant_id)
        return templates.TemplateResponse(
            request,
            "knowledge.html",
            {
                "tenant_id": str(tenant_id),
                "sources": sources,
                "active_page": "knowledge",
                "crawl_error": f"No pages could be retrieved from '{source}'.",
            },
        )

    result = await orchestrate_ingestion(
        request.app.state.pool,
        tenant_id,
        pages,
        trigger="dashboard_recrawl",
    )
    sources = await list_sources(request.app.state.pool, tenant_id)
    return templates.TemplateResponse(
        request,
        "knowledge.html",
        {
            "tenant_id": str(tenant_id),
            "sources": sources,
            "active_page": "knowledge",
            "recrawl_queued": bool(result["queued"]),
            "recrawl_noop": not result["queued"],
        },
    )


@router.post("/{tenant_id}/knowledge/delete", response_class=HTMLResponse)
async def knowledge_delete_source(
    tenant_id: uuid.UUID,
    request: Request,
    source: str = Form(...),
    auth_context: AuthContext = Depends(require_auth_context),
) -> HTMLResponse:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    await deactivate_source(request.app.state.pool, tenant_id, source)
    await request_rebuild(
        request.app.state.pool,
        tenant_id,
        trigger="dashboard_delete",
        changed_sources=[{"source_key": source, "content_hash": "deleted"}],
        force=True,
    )
    sources = await list_sources(request.app.state.pool, tenant_id)
    return templates.TemplateResponse(
        request,
        "knowledge.html",
        {
            "tenant_id": str(tenant_id),
            "sources": sources,
            "active_page": "knowledge",
            "delete_queued": True,
        },
    )
