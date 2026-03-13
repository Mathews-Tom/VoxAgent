from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from voxagent.knowledge.chunker import chunk_pages
from voxagent.knowledge.engine import KnowledgeEngine
from voxagent.knowledge.ingest import PageContent
from voxagent.metrics import KNOWLEDGE_INDEX_BUILDS
from voxagent.models import JobRecord
from voxagent.queries import enqueue_job

if TYPE_CHECKING:
    import asyncpg


def knowledge_storage_dir(tenant_id: uuid.UUID) -> Path:
    return Path("data") / str(tenant_id) / "knowledge"


def _chunk_counts_by_source(engine: KnowledgeEngine) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in getattr(engine, "_chunks", []):
        counts[chunk.source_url] = counts.get(chunk.source_url, 0) + 1
    return counts


async def _latest_source_versions(pool: asyncpg.Pool, tenant_id: uuid.UUID) -> list[asyncpg.Record]:
    return await pool.fetch(
        """
        SELECT DISTINCT ON (ks.id)
            ks.source_key,
            ks.source_type,
            ksv.id AS version_id,
            ksv.title,
            ksv.content_hash,
            ksv.content_text,
            ksv.created_at
        FROM knowledge_sources ks
        JOIN knowledge_source_versions ksv ON ksv.knowledge_source_id = ks.id
        WHERE ks.tenant_id = $1
          AND ks.is_active = TRUE
        ORDER BY ks.id, ksv.created_at DESC
        """,
        tenant_id,
    )


async def _upsert_source_versions(
    pool: asyncpg.Pool,
    tenant_id: uuid.UUID,
    pages: list[PageContent],
) -> list[dict[str, str]]:
    changed_sources: list[dict[str, str]] = []
    for page in pages:
        source_row = await pool.fetchrow(
            """
            INSERT INTO knowledge_sources (tenant_id, source_key, source_type, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (tenant_id, source_key)
            DO UPDATE SET source_type = EXCLUDED.source_type, updated_at = now()
            RETURNING *
            """,
            tenant_id,
            page.url,
            page.source_type,
        )
        latest_version = await pool.fetchrow(
            """
            SELECT *
            FROM knowledge_source_versions
            WHERE knowledge_source_id = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            source_row["id"],
        )
        if latest_version is None or latest_version["content_hash"] != page.content_hash:
            await pool.fetchrow(
                """
                INSERT INTO knowledge_source_versions (
                    knowledge_source_id,
                    title,
                    content_hash,
                    content_text,
                    metadata
                )
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                source_row["id"],
                page.title,
                page.content_hash,
                page.text,
                json.dumps({"source_url": page.url, "source_type": page.source_type}),
            )
            changed_sources.append(
                {
                    "source_key": page.url,
                    "content_hash": page.content_hash,
                }
            )
    return changed_sources


def _job_fingerprint(
    tenant_id: uuid.UUID,
    trigger: str,
    changed_sources: list[dict[str, str]],
) -> str:
    digest = hashlib.sha256()
    digest.update(str(tenant_id).encode())
    digest.update(trigger.encode())
    for item in sorted(changed_sources, key=lambda entry: entry["source_key"]):
        digest.update(item["source_key"].encode())
        digest.update(item["content_hash"].encode())
    return digest.hexdigest()[:16]


async def request_rebuild(
    pool: asyncpg.Pool,
    tenant_id: uuid.UUID,
    trigger: str,
    changed_sources: list[dict[str, str]],
    *,
    force: bool = False,
) -> JobRecord:
    fingerprint = (
        str(uuid.uuid4())
        if force
        else _job_fingerprint(tenant_id, trigger, changed_sources)
    )
    job = JobRecord(
        job_type="knowledge_rebuild",
        payload={
            "tenant_id": str(tenant_id),
            "trigger": trigger,
            "source_keys": [item["source_key"] for item in changed_sources],
        },
        idempotency_key=f"knowledge_rebuild:{tenant_id}:{fingerprint}",
    )
    return await enqueue_job(pool, job)


async def orchestrate_ingestion(
    pool: asyncpg.Pool,
    tenant_id: uuid.UUID,
    pages: list[PageContent],
    *,
    trigger: str,
) -> dict[str, object]:
    changed_sources = await _upsert_source_versions(pool, tenant_id, pages)
    if not changed_sources:
        return {
            "queued": False,
            "changed_sources": 0,
            "manifest": load_manifest(tenant_id),
        }

    job = await request_rebuild(pool, tenant_id, trigger, changed_sources)
    return {
        "queued": True,
        "changed_sources": len(changed_sources),
        "job_id": str(job.id),
    }


async def ingest_pages(
    pool: asyncpg.Pool,
    tenant_id: uuid.UUID,
    pages: list[PageContent],
) -> dict[str, object]:
    await _upsert_source_versions(pool, tenant_id, pages)
    latest_versions = await _latest_source_versions(pool, tenant_id)
    pages_for_build = [
        PageContent(
            url=row["source_key"],
            title=row["title"],
            html="",
            text=row["content_text"],
            content_hash=row["content_hash"],
            source_type=row["source_type"],
            source_version_id=str(row["version_id"]),
        )
        for row in latest_versions
    ]
    chunks = chunk_pages(pages_for_build)
    storage_dir = knowledge_storage_dir(tenant_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    engine = KnowledgeEngine(str(storage_dir))
    engine.build_index(chunks)
    manifest = {
        "tenant_id": str(tenant_id),
        "built_at": datetime.now(UTC).isoformat(),
        "chunk_count": len(chunks),
        "sources": [
            {
                "source_key": row["source_key"],
                "source_type": row["source_type"],
                "source_version_id": str(row["version_id"]),
                "title": row["title"],
                "content_hash": row["content_hash"],
            }
            for row in latest_versions
        ],
    }
    engine.write_manifest(manifest)
    await pool.execute(
        """
        INSERT INTO knowledge_indexes (tenant_id, artifact_manifest, chunk_count)
        VALUES ($1, $2, $3)
        """,
        tenant_id,
        json.dumps(manifest),
        len(chunks),
    )
    KNOWLEDGE_INDEX_BUILDS.labels(tenant_id=str(tenant_id), trigger="ingest").inc()
    return manifest


def load_manifest(tenant_id: uuid.UUID) -> dict[str, object]:
    engine = KnowledgeEngine(str(knowledge_storage_dir(tenant_id)))
    return engine.read_manifest()


async def rebuild_index(pool: asyncpg.Pool, tenant_id: uuid.UUID) -> dict[str, object]:
    latest_versions = await _latest_source_versions(pool, tenant_id)
    pages = [
        PageContent(
            url=row["source_key"],
            title=row["title"],
            html="",
            text=row["content_text"],
            content_hash=row["content_hash"],
            source_type=row["source_type"],
            source_version_id=str(row["version_id"]),
        )
        for row in latest_versions
    ]
    storage_dir = knowledge_storage_dir(tenant_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    engine = KnowledgeEngine(str(storage_dir))
    engine.build_index(chunk_pages(pages))
    manifest = {
        "tenant_id": str(tenant_id),
        "built_at": datetime.now(UTC).isoformat(),
        "chunk_count": len(getattr(engine, "_chunks", [])),
        "sources": [
            {
                "source_key": row["source_key"],
                "source_type": row["source_type"],
                "source_version_id": str(row["version_id"]),
                "title": row["title"],
                "content_hash": row["content_hash"],
            }
            for row in latest_versions
        ],
    }
    engine.write_manifest(manifest)
    await pool.execute(
        """
        INSERT INTO knowledge_indexes (tenant_id, artifact_manifest, chunk_count)
        VALUES ($1, $2, $3)
        """,
        tenant_id,
        json.dumps(manifest),
        manifest["chunk_count"],
    )
    KNOWLEDGE_INDEX_BUILDS.labels(tenant_id=str(tenant_id), trigger="rebuild").inc()
    return manifest


async def list_sources(pool: asyncpg.Pool, tenant_id: uuid.UUID) -> list[dict[str, object]]:
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (ks.id)
            ks.id,
            ks.source_key,
            ks.source_type,
            ks.is_active,
            ks.updated_at,
            ksv.id AS version_id,
            ksv.title,
            ksv.content_hash,
            ksv.created_at
        FROM knowledge_sources ks
        LEFT JOIN knowledge_source_versions ksv ON ksv.knowledge_source_id = ks.id
        WHERE ks.tenant_id = $1
        ORDER BY ks.id, ksv.created_at DESC NULLS LAST
        """,
        tenant_id,
    )
    engine = KnowledgeEngine(str(knowledge_storage_dir(tenant_id)))
    manifest = engine.read_manifest()
    if manifest:
        with suppress(FileNotFoundError):
            engine.load_index()
    chunk_counts = _chunk_counts_by_source(engine)
    return [
        {
            "name": row["source_key"],
            "title": row["title"] or row["source_key"],
            "source_type": row["source_type"],
            "source_version_id": str(row["version_id"]) if row["version_id"] else None,
            "content_hash": row["content_hash"],
            "chunk_count": chunk_counts.get(row["source_key"], 0),
            "is_active": row["is_active"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


async def delete_source(
    pool: asyncpg.Pool,
    tenant_id: uuid.UUID,
    source_key: str,
) -> dict[str, object]:
    await pool.execute(
        """
        UPDATE knowledge_sources
        SET is_active = FALSE, updated_at = now()
        WHERE tenant_id = $1 AND source_key = $2
        """,
        tenant_id,
        source_key,
    )
    return await rebuild_index(pool, tenant_id)


async def deactivate_source(pool: asyncpg.Pool, tenant_id: uuid.UUID, source_key: str) -> None:
    await pool.execute(
        """
        UPDATE knowledge_sources
        SET is_active = FALSE, updated_at = now()
        WHERE tenant_id = $1 AND source_key = $2
        """,
        tenant_id,
        source_key,
    )
