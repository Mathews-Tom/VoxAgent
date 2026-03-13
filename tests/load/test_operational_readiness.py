from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from voxagent.jobs.runner import enqueue_post_session_jobs, run_job_batch
from voxagent.knowledge.ingest import PageContent
from voxagent.knowledge.service import orchestrate_ingestion
from voxagent.models import ConversationRecord, TenantConfig
from voxagent.queries import create_conversation, create_tenant
from voxagent.server.middleware import InMemoryRateLimitStore, RateLimitMiddleware
from voxagent.server.routes.widget import router as widget_router

pytestmark = pytest.mark.load

_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest_asyncio.fixture
async def pool() -> AsyncGenerator[asyncpg.Pool, None]:
    if _TEST_DB_URL is None:
        pytest.skip("TEST_DATABASE_URL not set")
    p = await asyncpg.create_pool(_TEST_DB_URL, min_size=1, max_size=5, command_timeout=60)
    tables_exist = await p.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants')"
    )
    if not tables_exist:
        for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            await p.execute(sql_file.read_text())
    yield p
    await p.close()


def _make_widget_app() -> FastAPI:
    app = FastAPI()
    app.include_router(widget_router)
    app.add_middleware(RateLimitMiddleware, store=InMemoryRateLimitStore())
    config = MagicMock()
    config.livekit_api_key = "devkey"
    config.livekit_api_secret = "devsecret1234567890123456789012345678901234567890"
    config.livekit_url = "ws://localhost:7880"
    config.allow_localhost_widget_origins = True
    app.state.config = config
    app.state.pool = MagicMock()
    return app


def _make_rate_limited_probe_app(store: InMemoryRateLimitStore) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, store=store)

    @app.get("/api/token")
    async def probe() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.mark.asyncio
async def test_token_issuance_burst_handles_parallel_requests() -> None:
    app = _make_widget_app()
    tenant_id = uuid.uuid4()

    async def _request(idx: int) -> int:
        transport = ASGITransport(app=app, client=(f"10.0.0.{idx + 1}", 9000 + idx))
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/token",
                json={"tenant_id": str(tenant_id)},
                headers={"origin": "http://localhost:3000"},
            )
            return response.status_code

    with patch("voxagent.server.routes.widget.get_tenant") as mock_get_tenant:
        mock_get_tenant.return_value = TenantConfig(id=tenant_id, name="Acme", domain="acme.local")
        statuses = await asyncio.gather(*[_request(i) for i in range(40)])

    assert all(status == 200 for status in statuses)


@pytest.mark.asyncio
async def test_shared_rate_limit_store_enforces_global_limit_across_instances() -> None:
    shared_store = InMemoryRateLimitStore()
    app_a = AsyncClient(
        transport=ASGITransport(app=_make_rate_limited_probe_app(shared_store)),
        base_url="http://testserver",
    )
    app_b = AsyncClient(
        transport=ASGITransport(app=_make_rate_limited_probe_app(shared_store)),
        base_url="http://testserver",
    )
    async with app_a, app_b:
        for idx in range(30):
            client = app_a if idx % 2 == 0 else app_b
            response = await client.get(
                "/api/token",
                headers={"origin": "http://localhost:3000"},
            )
            assert response.status_code == 200

        blocked = await app_a.get("/api/token", headers={"origin": "http://localhost:3000"})

    assert blocked.status_code == 429


@pytest.mark.asyncio
async def test_concurrent_ingestion_and_job_processing_remain_idempotent(
    pool: asyncpg.Pool,
) -> None:
    tenant = await create_tenant(
        pool,
        TenantConfig(
            name=f"load-{uuid.uuid4().hex[:8]}",
            domain=f"{uuid.uuid4().hex[:8]}.example.com",
        ),
    )
    conversation = await create_conversation(
        pool,
        ConversationRecord(
            tenant_id=tenant.id,
            visitor_id="visitor-load",
            room_name="room-load",
            transcript=[{"role": "user", "content": "need pricing"}],
            started_at=datetime.now(UTC),
        ),
    )
    page = PageContent(
        url="https://acme.example/pricing",
        title="pricing",
        html="",
        text="Starter plan is $29/month.",
        content_hash="hash-pricing-load-v1",
        source_type="web",
    )

    await asyncio.gather(
        enqueue_post_session_jobs(pool, tenant.id, conversation.id, "visitor-load"),
        orchestrate_ingestion(pool, tenant.id, [page], trigger="load_test"),
        orchestrate_ingestion(pool, tenant.id, [page], trigger="load_test"),
    )
    with (
        patch("voxagent.leads.extract_lead", new_callable=AsyncMock, return_value=None),
        patch(
            "voxagent.memory.summarize_for_memory",
            new_callable=AsyncMock,
            return_value="Memory summary",
        ),
    ):
        await run_job_batch(pool, MagicMock(), limit=20)

    lead_count = await pool.fetchval(
        "SELECT COUNT(*) FROM leads WHERE conversation_id = $1",
        conversation.id,
    )
    version_count = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM knowledge_source_versions ksv
        JOIN knowledge_sources ks ON ks.id = ksv.knowledge_source_id
        WHERE ks.tenant_id = $1 AND ks.source_key = $2
        """,
        tenant.id,
        page.url,
    )

    assert lead_count <= 1
    assert version_count == 1
