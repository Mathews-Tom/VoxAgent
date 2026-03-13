from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
import pytest_asyncio

from voxagent.jobs.runner import run_job_batch
from voxagent.knowledge.ingest import PageContent
from voxagent.knowledge.service import load_manifest, orchestrate_ingestion
from voxagent.models import (
    ConversationEvent,
    ConversationRecord,
    LeadRecord,
    TenantConfig,
    VisitorMemory,
)
from voxagent.queries import (
    create_conversation,
    create_conversation_events,
    create_lead,
    create_tenant,
    delete_tenant,
    get_conversation,
    get_lead_by_conversation,
    get_tenant,
    get_tenant_by_domain,
    get_visitor_memory,
    list_conversation_events,
    list_conversations,
    list_leads,
    list_tenants,
    update_tenant,
    upsert_visitor_memory,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    _TEST_DB_URL is None,
    reason="TEST_DATABASE_URL not set",
)


@pytest_asyncio.fixture
async def pool() -> AsyncGenerator[asyncpg.Pool, None]:
    assert _TEST_DB_URL is not None
    p = await asyncpg.create_pool(_TEST_DB_URL, min_size=1, max_size=5, command_timeout=60)
    assert p is not None
    # Ensure schema exists (idempotent)
    tables_exist = await p.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants')"
    )
    if not tables_exist:
        for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            await p.execute(sql_file.read_text())
    yield p
    await p.close()


def _make_tenant(**overrides: object) -> TenantConfig:
    defaults: dict[str, object] = {
        "name": f"test-{uuid.uuid4().hex[:8]}",
        "domain": f"{uuid.uuid4().hex[:8]}.example.com",
    }
    defaults.update(overrides)
    return TenantConfig(**defaults)  # type: ignore[arg-type]


# ── Tenant Tests ──


class TestTenantQueries:
    @pytest.mark.asyncio
    async def test_create_and_get(self, pool: asyncpg.Pool) -> None:
        tenant = _make_tenant()
        created = await create_tenant(pool, tenant)
        assert created.name == tenant.name

        fetched = await get_tenant(pool, created.id)
        assert fetched is not None
        assert fetched.name == tenant.name

    @pytest.mark.asyncio
    async def test_list(self, pool: asyncpg.Pool) -> None:
        await create_tenant(pool, _make_tenant())
        tenants = await list_tenants(pool)
        assert len(tenants) >= 1

    @pytest.mark.asyncio
    async def test_update(self, pool: asyncpg.Pool) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        tenant.name = "updated-name"
        updated = await update_tenant(pool, tenant)
        assert updated.name == "updated-name"

    @pytest.mark.asyncio
    async def test_delete(self, pool: asyncpg.Pool) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        await delete_tenant(pool, tenant.id)
        assert await get_tenant(pool, tenant.id) is None

    @pytest.mark.asyncio
    async def test_get_by_domain(self, pool: asyncpg.Pool) -> None:
        domain = f"unique-{uuid.uuid4().hex[:8]}.com"
        tenant = await create_tenant(pool, _make_tenant(domain=domain))
        fetched = await get_tenant_by_domain(pool, domain)
        assert fetched is not None
        assert fetched.id == tenant.id


# ── Conversation Tests ──


class TestConversationQueries:
    @pytest.mark.asyncio
    async def test_create_and_get(self, pool: asyncpg.Pool) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        record = ConversationRecord(
            tenant_id=tenant.id,
            visitor_id="v1",
            room_name="room-1",
            transcript=[{"role": "user", "content": "hi"}],
            started_at=datetime.now(UTC),
        )
        created = await create_conversation(pool, record)
        assert created.room_name == "room-1"

        fetched = await get_conversation(pool, created.id)
        assert fetched is not None
        assert fetched.transcript == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_create_and_list_events(self, pool: asyncpg.Pool) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        conversation = await create_conversation(
            pool,
            ConversationRecord(
                tenant_id=tenant.id,
                visitor_id="v2",
                room_name="room-events",
                transcript=[{"role": "user", "content": "hello"}],
                started_at=datetime.now(UTC),
            ),
        )
        created_events = await create_conversation_events(
            pool,
            conversation.id,
            [
                ConversationEvent(
                    conversation_id=conversation.id,
                    role="user",
                    content="hello",
                    sequence_number=0,
                ),
                ConversationEvent(
                    conversation_id=conversation.id,
                    role="assistant",
                    content="hi there",
                    sequence_number=1,
                ),
            ],
        )

        assert len(created_events) == 2
        fetched_events = await list_conversation_events(pool, conversation.id)
        assert [event.content for event in fetched_events] == ["hello", "hi there"]

    @pytest.mark.asyncio
    async def test_list_with_pagination(self, pool: asyncpg.Pool) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        for i in range(3):
            await create_conversation(pool, ConversationRecord(
                tenant_id=tenant.id,
                visitor_id="v1",
                room_name=f"room-{i}",
                started_at=datetime.now(UTC),
            ))
        page = await list_conversations(pool, tenant.id, limit=2, offset=0)
        assert len(page) == 2
        page2 = await list_conversations(pool, tenant.id, limit=2, offset=2)
        assert len(page2) == 1


# ── Lead Tests ──


class TestLeadQueries:
    @pytest.mark.asyncio
    async def test_create_and_list(self, pool: asyncpg.Pool) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        conv = await create_conversation(pool, ConversationRecord(
            tenant_id=tenant.id,
            visitor_id="v1",
            room_name="room-1",
            started_at=datetime.now(UTC),
        ))
        lead = LeadRecord(
            tenant_id=tenant.id,
            conversation_id=conv.id,
            name="Alice",
            email="alice@test.com",
        )
        created = await create_lead(pool, lead)
        assert created.name == "Alice"

        leads = await list_leads(pool, tenant.id)
        assert len(leads) >= 1

    @pytest.mark.asyncio
    async def test_create_lead_is_idempotent_per_conversation(self, pool: asyncpg.Pool) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        conversation = await create_conversation(
            pool,
            ConversationRecord(
                tenant_id=tenant.id,
                visitor_id="v-idempotent",
                room_name="room-idempotent",
                started_at=datetime.now(UTC),
            ),
        )
        first = await create_lead(
            pool,
            LeadRecord(
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                name="Alice",
                email="alice@example.com",
            ),
        )
        second = await create_lead(
            pool,
            LeadRecord(
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                name="Alice Updated",
                email="alice@example.com",
            ),
        )

        assert first.id == second.id
        stored = await get_lead_by_conversation(pool, conversation.id)
        assert stored is not None
        assert stored.name == "Alice Updated"

    @pytest.mark.asyncio
    async def test_pagination(self, pool: asyncpg.Pool) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        for i in range(3):
            conversation = await create_conversation(
                pool,
                ConversationRecord(
                    tenant_id=tenant.id,
                    visitor_id=f"v{i}",
                    room_name=f"r{i}",
                    started_at=datetime.now(UTC),
                ),
            )
            await create_lead(
                pool,
                LeadRecord(
                    tenant_id=tenant.id,
                    conversation_id=conversation.id,
                    name=f"Lead{i}",
                ),
            )
        page = await list_leads(pool, tenant.id, limit=2, offset=0)
        assert len(page) == 2


class TestManagedKnowledgeIngestion:
    @pytest.mark.asyncio
    async def test_duplicate_content_does_not_create_new_source_version(
        self, pool: asyncpg.Pool
    ) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        page = PageContent(
            url="https://acme.example/pricing",
            title="pricing",
            html="",
            text="Starter plan is $29/month.",
            content_hash="hash-pricing-v1",
            source_type="web",
        )

        first = await orchestrate_ingestion(pool, tenant.id, [page], trigger="integration")
        assert first["queued"] is True
        with patch(
            "voxagent.memory.summarize_for_memory",
            new_callable=AsyncMock,
            return_value="Memory summary",
        ):
            await run_job_batch(pool, MagicMock(), limit=10)

        second = await orchestrate_ingestion(pool, tenant.id, [page], trigger="integration")
        assert second["queued"] is False

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
        assert version_count == 1

    @pytest.mark.asyncio
    async def test_partial_rebuild_only_versions_changed_source(self, pool: asyncpg.Pool) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        pricing_v1 = PageContent(
            url="https://acme.example/pricing",
            title="pricing",
            html="",
            text="Starter plan is $29/month.",
            content_hash="hash-pricing-v1",
            source_type="web",
        )
        faq_v1 = PageContent(
            url="https://acme.example/faq",
            title="faq",
            html="",
            text="We support English and Hindi.",
            content_hash="hash-faq-v1",
            source_type="web",
        )

        initial = await orchestrate_ingestion(
            pool,
            tenant.id,
            [pricing_v1, faq_v1],
            trigger="integration",
        )
        assert initial["queued"] is True
        with patch(
            "voxagent.memory.summarize_for_memory",
            new_callable=AsyncMock,
            return_value="Memory summary",
        ):
            await run_job_batch(pool, MagicMock(), limit=10)

        before_rows = await pool.fetch(
            """
            SELECT ks.source_key, ksv.id AS version_id
            FROM knowledge_sources ks
            JOIN LATERAL (
                SELECT id
                FROM knowledge_source_versions
                WHERE knowledge_source_id = ks.id
                ORDER BY created_at DESC
                LIMIT 1
            ) ksv ON TRUE
            WHERE ks.tenant_id = $1
            ORDER BY ks.source_key
            """,
            tenant.id,
        )
        before_versions = {row["source_key"]: row["version_id"] for row in before_rows}

        pricing_v2 = PageContent(
            url="https://acme.example/pricing",
            title="pricing",
            html="",
            text="Starter plan is $39/month.",
            content_hash="hash-pricing-v2",
            source_type="web",
        )
        partial = await orchestrate_ingestion(pool, tenant.id, [pricing_v2], trigger="integration")
        assert partial["queued"] is True
        with patch(
            "voxagent.memory.summarize_for_memory",
            new_callable=AsyncMock,
            return_value="Memory summary",
        ):
            await run_job_batch(pool, MagicMock(), limit=10)

        after_rows = await pool.fetch(
            """
            SELECT ks.source_key, ksv.id AS version_id
            FROM knowledge_sources ks
            JOIN LATERAL (
                SELECT id
                FROM knowledge_source_versions
                WHERE knowledge_source_id = ks.id
                ORDER BY created_at DESC
                LIMIT 1
            ) ksv ON TRUE
            WHERE ks.tenant_id = $1
            ORDER BY ks.source_key
            """,
            tenant.id,
        )
        after_versions = {row["source_key"]: row["version_id"] for row in after_rows}

        assert before_versions["https://acme.example/pricing"] != after_versions["https://acme.example/pricing"]
        assert before_versions["https://acme.example/faq"] == after_versions["https://acme.example/faq"]

        manifest = load_manifest(tenant.id)
        manifest_sources = {source["source_key"] for source in manifest["sources"]}
        assert manifest_sources == {
            "https://acme.example/pricing",
            "https://acme.example/faq",
        }


# ── Visitor Memory Tests ──


class TestVisitorMemoryQueries:
    @pytest.mark.asyncio
    async def test_upsert_create(self, pool: asyncpg.Pool) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        mem = VisitorMemory(
            tenant_id=tenant.id,
            visitor_id="v1",
            summary="First visit.",
            turn_count=3,
        )
        created = await upsert_visitor_memory(pool, mem)
        assert created.summary == "First visit."

    @pytest.mark.asyncio
    async def test_upsert_update(self, pool: asyncpg.Pool) -> None:
        tenant = await create_tenant(pool, _make_tenant())
        mem = VisitorMemory(
            tenant_id=tenant.id, visitor_id="v2", summary="Initial.", turn_count=1,
        )
        await upsert_visitor_memory(pool, mem)
        mem.summary = "Updated."
        mem.turn_count = 5
        updated = await upsert_visitor_memory(pool, mem)
        assert updated.summary == "Updated."
        assert updated.turn_count == 5

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, pool: asyncpg.Pool) -> None:
        result = await get_visitor_memory(pool, uuid.uuid4(), "nonexistent")
        assert result is None
