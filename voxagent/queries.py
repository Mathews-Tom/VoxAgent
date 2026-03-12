from __future__ import annotations

import json
import uuid

import asyncpg

from voxagent.models import (
    ConversationRecord,
    LeadRecord,
    LLMConfig,
    STTConfig,
    TenantConfig,
    TTSConfig,
)


def _row_to_tenant(row: asyncpg.Record) -> TenantConfig:
    return TenantConfig(
        id=row["id"],
        name=row["name"],
        domain=row["domain"],
        password_hash=row["password_hash"],
        stt=STTConfig.model_validate(json.loads(row["stt_config"]) if row["stt_config"] else {}),
        llm=LLMConfig.model_validate(json.loads(row["llm_config"]) if row["llm_config"] else {}),
        tts=TTSConfig.model_validate(json.loads(row["tts_config"]) if row["tts_config"] else {}),
        greeting=row["greeting"],
        widget_color=row["widget_color"],
        widget_position=row["widget_position"],
        allowed_origins=json.loads(row["allowed_origins"]) if row["allowed_origins"] else [],
        created_at=row["created_at"],
    )


# ── Tenants ──────────────────────────────────────────────────────────────────


async def get_tenant(pool: asyncpg.Pool, tenant_id: uuid.UUID) -> TenantConfig | None:
    row = await pool.fetchrow("SELECT * FROM tenants WHERE id = $1", tenant_id)
    if row is None:
        return None
    return _row_to_tenant(row)


async def get_tenant_by_domain(pool: asyncpg.Pool, domain: str) -> TenantConfig | None:
    row = await pool.fetchrow("SELECT * FROM tenants WHERE domain = $1", domain)
    if row is None:
        return None
    return _row_to_tenant(row)


async def list_tenants(pool: asyncpg.Pool) -> list[TenantConfig]:
    rows = await pool.fetch("SELECT * FROM tenants ORDER BY created_at DESC")
    return [_row_to_tenant(r) for r in rows]


async def create_tenant(pool: asyncpg.Pool, tenant: TenantConfig) -> TenantConfig:
    row = await pool.fetchrow(
        """
        INSERT INTO tenants (name, domain, password_hash, stt_config, llm_config,
                             tts_config, greeting, widget_color, widget_position,
                             allowed_origins)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING *
        """,
        tenant.name,
        tenant.domain,
        tenant.password_hash,
        json.dumps(tenant.stt.model_dump()),
        json.dumps(tenant.llm.model_dump()),
        json.dumps(tenant.tts.model_dump()),
        tenant.greeting,
        tenant.widget_color,
        tenant.widget_position,
        json.dumps(tenant.allowed_origins),
    )
    return _row_to_tenant(row)


async def update_tenant(pool: asyncpg.Pool, tenant: TenantConfig) -> TenantConfig:
    row = await pool.fetchrow(
        """
        UPDATE tenants
        SET name = $2, domain = $3, password_hash = $4, stt_config = $5,
            llm_config = $6, tts_config = $7, greeting = $8, widget_color = $9,
            widget_position = $10, allowed_origins = $11
        WHERE id = $1
        RETURNING *
        """,
        tenant.id,
        tenant.name,
        tenant.domain,
        tenant.password_hash,
        json.dumps(tenant.stt.model_dump()),
        json.dumps(tenant.llm.model_dump()),
        json.dumps(tenant.tts.model_dump()),
        tenant.greeting,
        tenant.widget_color,
        tenant.widget_position,
        json.dumps(tenant.allowed_origins),
    )
    if row is None:
        msg = f"Tenant {tenant.id} not found"
        raise RuntimeError(msg)
    return _row_to_tenant(row)


async def delete_tenant(pool: asyncpg.Pool, tenant_id: uuid.UUID) -> None:
    result = await pool.execute("DELETE FROM tenants WHERE id = $1", tenant_id)
    if result == "DELETE 0":
        msg = f"Tenant {tenant_id} not found"
        raise RuntimeError(msg)


# ── Conversations ────────────────────────────────────────────────────────────


async def create_conversation(
    pool: asyncpg.Pool, record: ConversationRecord
) -> ConversationRecord:
    row = await pool.fetchrow(
        """
        INSERT INTO conversations (tenant_id, visitor_id, room_name, transcript,
                                   language, duration_seconds, started_at, ended_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        record.tenant_id,
        record.visitor_id,
        record.room_name,
        json.dumps(record.transcript),
        record.language,
        record.duration_seconds,
        record.started_at,
        record.ended_at,
    )
    return ConversationRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        visitor_id=row["visitor_id"],
        room_name=row["room_name"],
        transcript=json.loads(row["transcript"]) if row["transcript"] else [],
        language=row["language"],
        duration_seconds=row["duration_seconds"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
    )


async def list_conversations(
    pool: asyncpg.Pool,
    tenant_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[ConversationRecord]:
    rows = await pool.fetch(
        """
        SELECT * FROM conversations
        WHERE tenant_id = $1
        ORDER BY started_at DESC
        LIMIT $2 OFFSET $3
        """,
        tenant_id,
        limit,
        offset,
    )
    return [
        ConversationRecord(
            id=r["id"],
            tenant_id=r["tenant_id"],
            visitor_id=r["visitor_id"],
            room_name=r["room_name"],
            transcript=json.loads(r["transcript"]) if r["transcript"] else [],
            language=r["language"],
            duration_seconds=r["duration_seconds"],
            started_at=r["started_at"],
            ended_at=r["ended_at"],
        )
        for r in rows
    ]


async def get_conversation(
    pool: asyncpg.Pool, conversation_id: uuid.UUID
) -> ConversationRecord | None:
    row = await pool.fetchrow("SELECT * FROM conversations WHERE id = $1", conversation_id)
    if row is None:
        return None
    return ConversationRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        visitor_id=row["visitor_id"],
        room_name=row["room_name"],
        transcript=json.loads(row["transcript"]) if row["transcript"] else [],
        language=row["language"],
        duration_seconds=row["duration_seconds"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
    )


# ── Leads ────────────────────────────────────────────────────────────────────


async def create_lead(pool: asyncpg.Pool, lead: LeadRecord) -> LeadRecord:
    row = await pool.fetchrow(
        """
        INSERT INTO leads (tenant_id, conversation_id, name, email, phone, intent, summary)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING *
        """,
        lead.tenant_id,
        lead.conversation_id,
        lead.name,
        lead.email,
        lead.phone,
        lead.intent,
        lead.summary,
    )
    return LeadRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        conversation_id=row["conversation_id"],
        name=row["name"],
        email=row["email"],
        phone=row["phone"],
        intent=row["intent"],
        summary=row["summary"],
        extracted_at=row["extracted_at"],
    )


async def list_leads(
    pool: asyncpg.Pool,
    tenant_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[LeadRecord]:
    rows = await pool.fetch(
        """
        SELECT * FROM leads
        WHERE tenant_id = $1
        ORDER BY extracted_at DESC
        LIMIT $2 OFFSET $3
        """,
        tenant_id,
        limit,
        offset,
    )
    return [
        LeadRecord(
            id=r["id"],
            tenant_id=r["tenant_id"],
            conversation_id=r["conversation_id"],
            name=r["name"],
            email=r["email"],
            phone=r["phone"],
            intent=r["intent"],
            summary=r["summary"],
            extracted_at=r["extracted_at"],
        )
        for r in rows
    ]
