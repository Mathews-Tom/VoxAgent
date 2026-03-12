from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from voxagent.knowledge.chunker import chunk_pages
from voxagent.knowledge.engine import KnowledgeEngine
from voxagent.knowledge.ingest import crawl_website, ingest_files
from voxagent.server.auth import require_auth

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/dashboard")

_SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}


def _knowledge_dir(tenant_id: uuid.UUID) -> Path:
    return Path("data") / str(tenant_id) / "knowledge"


def _load_sources(knowledge_dir: Path) -> list[dict[str, object]]:
    chunks_file = knowledge_dir / "chunks.json"
    if not chunks_file.exists():
        return []

    with chunks_file.open(encoding="utf-8") as fh:
        chunks = json.load(fh)

    counts: dict[str, int] = {}
    for chunk in chunks:
        url = chunk.get("source_url", "unknown")
        counts[url] = counts.get(url, 0) + 1

    return [{"name": url, "chunk_count": count} for url, count in counts.items()]


@router.get("/{tenant_id}/knowledge", response_class=HTMLResponse)
async def knowledge_page(
    tenant_id: uuid.UUID,
    request: Request,
    auth_tenant_id: uuid.UUID = Depends(require_auth),
) -> HTMLResponse:
    if auth_tenant_id != tenant_id:
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
    auth_tenant_id: uuid.UUID = Depends(require_auth),
) -> HTMLResponse:
    if auth_tenant_id != tenant_id:
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

    chunks = chunk_pages(pages)
    storage_dir = _knowledge_dir(tenant_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    engine = KnowledgeEngine(str(storage_dir))

    if (storage_dir / "chunks.json").exists():
        engine.load_index()
        existing_chunks = engine._chunks  # noqa: SLF001
        all_chunks = existing_chunks + chunks
    else:
        all_chunks = chunks

    engine.build_index(all_chunks)
    engine.update_hash_map(pages)

    sources = _load_sources(storage_dir)
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
    auth_tenant_id: uuid.UUID = Depends(require_auth),
) -> HTMLResponse:
    if auth_tenant_id != tenant_id:
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

    chunks = chunk_pages(pages)
    storage_dir = _knowledge_dir(tenant_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    engine = KnowledgeEngine(str(storage_dir))

    if (storage_dir / "chunks.json").exists():
        engine.load_index()
        existing_chunks = engine._chunks  # noqa: SLF001
        all_chunks = existing_chunks + chunks
    else:
        all_chunks = chunks

    engine.build_index(all_chunks)
    engine.update_hash_map(pages)

    sources = _load_sources(storage_dir)
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
