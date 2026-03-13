from __future__ import annotations

import json
import uuid

import asyncpg

from voxagent.models import (
    AdminRole,
    AdminUser,
    ConversationRecord,
    ConfigAuditLogEntry,
    JobRecord,
    JobStatus,
    LeadRecord,
    LLMConfig,
    MCPServerConfig,
    STTConfig,
    TenantConfig,
    TenantMembership,
    TTSConfig,
    VisitorMemory,
)


def _row_to_tenant(row: asyncpg.Record) -> TenantConfig:
    mcp_raw = json.loads(row["mcp_servers"]) if row["mcp_servers"] else []
    return TenantConfig(
        id=row["id"],
        name=row["name"],
        domain=row["domain"],
        is_active=row["is_active"],
        password_hash=row["password_hash"],
        stt=STTConfig.model_validate(json.loads(row["stt_config"]) if row["stt_config"] else {}),
        llm=LLMConfig.model_validate(json.loads(row["llm_config"]) if row["llm_config"] else {}),
        tts=TTSConfig.model_validate(json.loads(row["tts_config"]) if row["tts_config"] else {}),
        greeting=row["greeting"],
        widget_color=row["widget_color"],
        widget_position=row["widget_position"],
        allowed_origins=json.loads(row["allowed_origins"]) if row["allowed_origins"] else [],
        webhook_url=row["webhook_url"],
        mcp_servers=[MCPServerConfig.model_validate(s) for s in mcp_raw],
        created_at=row["created_at"],
    )


def _row_to_admin_user(row: asyncpg.Record) -> AdminUser:
    return AdminUser(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        password_hash_version=row["password_hash_version"],
        is_platform_admin=row["is_platform_admin"],
        is_active=row["is_active"],
        created_at=row["created_at"],
    )


def _row_to_membership(row: asyncpg.Record) -> TenantMembership:
    return TenantMembership(
        id=row["id"],
        admin_user_id=row["admin_user_id"],
        tenant_id=row["tenant_id"],
        role=AdminRole(row["role"]),
        created_at=row["created_at"],
    )


def _row_to_job(row: asyncpg.Record) -> JobRecord:
    return JobRecord(
        id=row["id"],
        job_type=row["job_type"],
        payload=json.loads(row["payload"]) if row["payload"] else {},
        status=JobStatus(row["status"]),
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        run_after=row["run_after"],
        idempotency_key=row["idempotency_key"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
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
        INSERT INTO tenants (name, domain, is_active, password_hash, stt_config, llm_config,
                             tts_config, greeting, widget_color, widget_position,
                             allowed_origins, webhook_url, mcp_servers)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        RETURNING *
        """,
        tenant.name,
        tenant.domain,
        tenant.is_active,
        tenant.password_hash,
        json.dumps(tenant.stt.model_dump()),
        json.dumps(tenant.llm.model_dump()),
        json.dumps(tenant.tts.model_dump()),
        tenant.greeting,
        tenant.widget_color,
        tenant.widget_position,
        json.dumps(tenant.allowed_origins),
        tenant.webhook_url,
        json.dumps([s.model_dump() for s in tenant.mcp_servers]),
    )
    return _row_to_tenant(row)


async def update_tenant(pool: asyncpg.Pool, tenant: TenantConfig) -> TenantConfig:
    row = await pool.fetchrow(
        """
        UPDATE tenants
        SET name = $2, domain = $3, is_active = $4, password_hash = $5, stt_config = $6,
            llm_config = $7, tts_config = $8, greeting = $9, widget_color = $10,
            widget_position = $11, allowed_origins = $12, webhook_url = $13,
            mcp_servers = $14
        WHERE id = $1
        RETURNING *
        """,
        tenant.id,
        tenant.name,
        tenant.domain,
        tenant.is_active,
        tenant.password_hash,
        json.dumps(tenant.stt.model_dump()),
        json.dumps(tenant.llm.model_dump()),
        json.dumps(tenant.tts.model_dump()),
        tenant.greeting,
        tenant.widget_color,
        tenant.widget_position,
        json.dumps(tenant.allowed_origins),
        tenant.webhook_url,
        json.dumps([s.model_dump() for s in tenant.mcp_servers]),
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


# ── Admins / Memberships ────────────────────────────────────────────────────


async def get_admin_user_by_email(pool: asyncpg.Pool, email: str) -> AdminUser | None:
    row = await pool.fetchrow("SELECT * FROM admin_users WHERE email = $1", email.lower())
    if row is None:
        return None
    return _row_to_admin_user(row)


async def get_admin_user(pool: asyncpg.Pool, admin_user_id: uuid.UUID) -> AdminUser | None:
    row = await pool.fetchrow("SELECT * FROM admin_users WHERE id = $1", admin_user_id)
    if row is None:
        return None
    return _row_to_admin_user(row)


async def list_tenant_memberships(
    pool: asyncpg.Pool,
    admin_user_id: uuid.UUID,
) -> list[TenantMembership]:
    rows = await pool.fetch(
        "SELECT * FROM tenant_memberships WHERE admin_user_id = $1 ORDER BY created_at ASC",
        admin_user_id,
    )
    return [_row_to_membership(row) for row in rows]


async def create_admin_user(
    pool: asyncpg.Pool,
    admin_user: AdminUser,
) -> AdminUser:
    row = await pool.fetchrow(
        """
        INSERT INTO admin_users (
            email,
            password_hash,
            password_hash_version,
            is_platform_admin,
            is_active
        )
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        admin_user.email.lower(),
        admin_user.password_hash,
        admin_user.password_hash_version,
        admin_user.is_platform_admin,
        admin_user.is_active,
    )
    return _row_to_admin_user(row)


async def update_admin_user_password(
    pool: asyncpg.Pool,
    admin_user_id: uuid.UUID,
    password_hash: str,
    password_hash_version: str,
) -> AdminUser:
    row = await pool.fetchrow(
        """
        UPDATE admin_users
        SET password_hash = $2, password_hash_version = $3
        WHERE id = $1
        RETURNING *
        """,
        admin_user_id,
        password_hash,
        password_hash_version,
    )
    if row is None:
        msg = f"Admin user {admin_user_id} not found"
        raise RuntimeError(msg)
    return _row_to_admin_user(row)


async def create_tenant_membership(
    pool: asyncpg.Pool,
    membership: TenantMembership,
) -> TenantMembership:
    row = await pool.fetchrow(
        """
        INSERT INTO tenant_memberships (admin_user_id, tenant_id, role)
        VALUES ($1, $2, $3)
        RETURNING *
        """,
        membership.admin_user_id,
        membership.tenant_id,
        membership.role.value,
    )
    return _row_to_membership(row)


async def create_admin_user_with_membership(
    pool: asyncpg.Pool,
    admin_user: AdminUser,
    tenant_id: uuid.UUID | None,
    role: AdminRole | None,
) -> tuple[AdminUser, TenantMembership | None]:
    async with pool.acquire() as conn:
        async with conn.transaction():
            admin_row = await conn.fetchrow(
                """
                INSERT INTO admin_users (
                    email,
                    password_hash,
                    password_hash_version,
                    is_platform_admin,
                    is_active
                )
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                admin_user.email.lower(),
                admin_user.password_hash,
                admin_user.password_hash_version,
                admin_user.is_platform_admin,
                admin_user.is_active,
            )
            created_admin = _row_to_admin_user(admin_row)
            membership: TenantMembership | None = None
            if tenant_id is not None and role is not None:
                membership_row = await conn.fetchrow(
                    """
                    INSERT INTO tenant_memberships (admin_user_id, tenant_id, role)
                    VALUES ($1, $2, $3)
                    RETURNING *
                    """,
                    created_admin.id,
                    tenant_id,
                    role.value,
                )
                membership = _row_to_membership(membership_row)
    return created_admin, membership


async def create_tenant_with_admin(
    pool: asyncpg.Pool,
    tenant: TenantConfig,
    admin_user: AdminUser,
    role: AdminRole = AdminRole.TENANT_ADMIN,
) -> tuple[TenantConfig, AdminUser, TenantMembership]:
    async with pool.acquire() as conn:
        async with conn.transaction():
            tenant_row = await conn.fetchrow(
                """
                INSERT INTO tenants (
                    name,
                    domain,
                    is_active,
                    password_hash,
                    stt_config,
                    llm_config,
                    tts_config,
                    greeting,
                    widget_color,
                    widget_position,
                    allowed_origins,
                    webhook_url,
                    mcp_servers
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                RETURNING *
                """,
                tenant.name,
                tenant.domain,
                tenant.is_active,
                tenant.password_hash,
                json.dumps(tenant.stt.model_dump()),
                json.dumps(tenant.llm.model_dump()),
                json.dumps(tenant.tts.model_dump()),
                tenant.greeting,
                tenant.widget_color,
                tenant.widget_position,
                json.dumps(tenant.allowed_origins),
                tenant.webhook_url,
                json.dumps([server.model_dump() for server in tenant.mcp_servers]),
            )
            created_tenant = _row_to_tenant(tenant_row)
            admin_row = await conn.fetchrow(
                """
                INSERT INTO admin_users (
                    email,
                    password_hash,
                    password_hash_version,
                    is_platform_admin,
                    is_active
                )
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                admin_user.email.lower(),
                admin_user.password_hash,
                admin_user.password_hash_version,
                admin_user.is_platform_admin,
                admin_user.is_active,
            )
            created_admin = _row_to_admin_user(admin_row)
            membership_row = await conn.fetchrow(
                """
                INSERT INTO tenant_memberships (admin_user_id, tenant_id, role)
                VALUES ($1, $2, $3)
                RETURNING *
                """,
                created_admin.id,
                created_tenant.id,
                role.value,
            )
            membership = _row_to_membership(membership_row)
    return created_tenant, created_admin, membership


async def create_config_audit_log(
    pool: asyncpg.Pool,
    entry: ConfigAuditLogEntry,
) -> ConfigAuditLogEntry:
    row = await pool.fetchrow(
        """
        INSERT INTO config_audit_log (actor_admin_user_id, tenant_id, action, diff_summary)
        VALUES ($1, $2, $3, $4)
        RETURNING *
        """,
        entry.actor_admin_user_id,
        entry.tenant_id,
        entry.action,
        entry.diff_summary,
    )
    return ConfigAuditLogEntry(
        id=row["id"],
        actor_admin_user_id=row["actor_admin_user_id"],
        tenant_id=row["tenant_id"],
        action=row["action"],
        diff_summary=row["diff_summary"],
        created_at=row["created_at"],
    )


# ── Jobs ────────────────────────────────────────────────────────────────────


async def enqueue_job(pool: asyncpg.Pool, job: JobRecord) -> JobRecord:
    row = await pool.fetchrow(
        """
        INSERT INTO jobs (
            job_type,
            payload,
            status,
            attempt_count,
            max_attempts,
            run_after,
            idempotency_key,
            last_error
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (idempotency_key)
        DO UPDATE SET updated_at = now()
        RETURNING *
        """,
        job.job_type,
        json.dumps(job.payload),
        job.status.value,
        job.attempt_count,
        job.max_attempts,
        job.run_after,
        job.idempotency_key,
        job.last_error,
    )
    return _row_to_job(row)


async def claim_due_jobs(pool: asyncpg.Pool, limit: int = 10) -> list[JobRecord]:
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                WITH due AS (
                    SELECT id
                    FROM jobs
                    WHERE status IN ('pending', 'failed')
                      AND run_after <= now()
                      AND attempt_count < max_attempts
                    ORDER BY run_after ASC, created_at ASC
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE jobs
                SET status = 'running',
                    attempt_count = attempt_count + 1,
                    updated_at = now(),
                    last_error = NULL
                WHERE id IN (SELECT id FROM due)
                RETURNING *
                """,
                limit,
            )
    return [_row_to_job(row) for row in rows]


async def mark_job_succeeded(pool: asyncpg.Pool, job_id: uuid.UUID) -> None:
    await pool.execute(
        """
        UPDATE jobs
        SET status = 'succeeded',
            updated_at = now(),
            last_error = NULL
        WHERE id = $1
        """,
        job_id,
    )


async def mark_job_failed(
    pool: asyncpg.Pool,
    job: JobRecord,
    error: str,
    retry_after_seconds: int = 30,
) -> None:
    status = JobStatus.FAILED if job.attempt_count < job.max_attempts else JobStatus.DEAD_LETTER
    await pool.execute(
        """
        UPDATE jobs
        SET status = $2,
            last_error = $3,
            run_after = now() + make_interval(secs => $4),
            updated_at = now()
        WHERE id = $1
        """,
        job.id,
        status.value,
        error,
        retry_after_seconds,
    )


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


# ── Visitor Memory ──────────────────────────────────────────────────────────


async def get_visitor_memory(
    pool: asyncpg.Pool,
    tenant_id: uuid.UUID,
    visitor_id: str,
) -> VisitorMemory | None:
    row = await pool.fetchrow(
        "SELECT * FROM visitor_memories WHERE tenant_id = $1 AND visitor_id = $2",
        tenant_id,
        visitor_id,
    )
    if row is None:
        return None
    return VisitorMemory(
        id=row["id"],
        tenant_id=row["tenant_id"],
        visitor_id=row["visitor_id"],
        summary=row["summary"],
        turn_count=row["turn_count"],
        updated_at=row["updated_at"],
    )


async def upsert_visitor_memory(
    pool: asyncpg.Pool,
    memory: VisitorMemory,
) -> VisitorMemory:
    row = await pool.fetchrow(
        """
        INSERT INTO visitor_memories (tenant_id, visitor_id, summary, turn_count, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (tenant_id, visitor_id)
        DO UPDATE SET summary = $3, turn_count = $4, updated_at = NOW()
        RETURNING *
        """,
        memory.tenant_id,
        memory.visitor_id,
        memory.summary,
        memory.turn_count,
    )
    return VisitorMemory(
        id=row["id"],
        tenant_id=row["tenant_id"],
        visitor_id=row["visitor_id"],
        summary=row["summary"],
        turn_count=row["turn_count"],
        updated_at=row["updated_at"],
    )
