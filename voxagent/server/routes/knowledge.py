from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from voxagent.knowledge.ingest import crawl_website, ingest_files
from voxagent.knowledge.service import ingest_pages as ingest_pages_service
from voxagent.knowledge.service import knowledge_storage_dir, load_manifest
from voxagent.models import AuthContext
from voxagent.server.auth import require_auth_context

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/dashboard")

_SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}


def _knowledge_dir(tenant_id: uuid.UUID) -> Path:
    return knowledge_storage_dir(tenant_id)


def _load_sources(knowledge_dir: Path) -> list[dict[str, object]]:
    manifest = load_manifest(uuid.UUID(knowledge_dir.parent.name))
    sources = manifest.get("sources", [])
    if not sources:
        return []
    counts: dict[str, int] = {}
    for source in sources:
        source_key = str(source.get("source_key", "unknown"))
        counts[source_key] = counts.get(source_key, 0) + 1
    return [{"name": key, "chunk_count": count} for key, count in counts.items()]


@router.get("/{tenant_id}/knowledge", response_class=HTMLResponse)
async def knowledge_page(
    tenant_id: uuid.UUID,
    request: Request,
    auth_context: AuthContext = Depends(require_auth_context),
) -> HTMLResponse:
    if not auth_context.can_access_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    sources = _load_sources(_knowledge_dir(tenant_id))

    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
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
        sources = _load_sources(_knowledge_dir(tenant_id))
        return templates.TemplateResponse(
            "knowledge.html",
            {
                "request": request,
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

    await ingest_pages_service(request.app.state.pool, tenant_id, pages)

    sources = _load_sources(_knowledge_dir(tenant_id))
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tenant_id": str(tenant_id),
            "sources": sources,
            "active_page": "knowledge",
            "upload_success": True,
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
        sources = _load_sources(_knowledge_dir(tenant_id))
        return templates.TemplateResponse(
            "knowledge.html",
            {
                "request": request,
                "tenant_id": str(tenant_id),
                "sources": sources,
                "active_page": "knowledge",
                "crawl_error": f"No pages could be retrieved from '{url}'.",
            },
        )

    await ingest_pages_service(request.app.state.pool, tenant_id, pages)

    sources = _load_sources(_knowledge_dir(tenant_id))
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tenant_id": str(tenant_id),
            "sources": sources,
            "active_page": "knowledge",
            "crawl_success": True,
        },
    )
