from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

from voxagent.knowledge.chunker import chunk_pages
from voxagent.knowledge.engine import KnowledgeEngine
from voxagent.knowledge.ingest import PageContent


def knowledge_storage_dir(tenant_id: uuid.UUID) -> Path:
    return Path("data") / str(tenant_id) / "knowledge"


async def ingest_pages(
    pool: asyncpg.Pool,
    tenant_id: uuid.UUID,
    pages: list[PageContent],
) -> dict[str, object]:
    source_rows = []
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
            version_row = await pool.fetchrow(
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
        else:
            version_row = latest_version
        source_rows.append((source_row, version_row))

    latest_versions = await pool.fetch(
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
    return manifest


def load_manifest(tenant_id: uuid.UUID) -> dict[str, object]:
    engine = KnowledgeEngine(str(knowledge_storage_dir(tenant_id)))
    return engine.read_manifest()
