from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from voxagent.agent.handoff import HandoffDetector, fire_handoff_webhook
from voxagent.knowledge.service import rebuild_index
from voxagent.metrics import JOB_DURATION, JOB_OUTCOMES
from voxagent.models import JobRecord, JobStatus, VisitorMemory
from voxagent.queries import (
    claim_due_jobs,
    enqueue_job,
    get_conversation,
    get_lead,
    get_tenant,
    get_visitor_memory,
    list_conversation_events,
    mark_job_failed,
    mark_job_succeeded,
    upsert_visitor_memory,
)

if TYPE_CHECKING:
    import asyncpg

    from voxagent.config import Config

logger = logging.getLogger(__name__)


async def enqueue_post_session_jobs(
    pool: asyncpg.Pool,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    visitor_id: str,
) -> list[JobRecord]:
    jobs = [
        JobRecord(
            job_type="lead_extraction",
            payload={
                "tenant_id": str(tenant_id),
                "conversation_id": str(conversation_id),
                "visitor_id": visitor_id,
            },
            idempotency_key=f"lead_extraction:{conversation_id}",
        ),
        JobRecord(
            job_type="visitor_memory",
            payload={
                "tenant_id": str(tenant_id),
                "conversation_id": str(conversation_id),
                "visitor_id": visitor_id,
            },
            idempotency_key=f"visitor_memory:{conversation_id}",
        ),
        JobRecord(
            job_type="handoff_dispatch",
            payload={
                "tenant_id": str(tenant_id),
                "conversation_id": str(conversation_id),
            },
            idempotency_key=f"handoff_dispatch:{conversation_id}",
        ),
    ]
    return [await enqueue_job(pool, job) for job in jobs]


async def run_job_batch(pool: asyncpg.Pool, app_config: Config, limit: int = 10) -> list[JobRecord]:
    claimed_jobs = await claim_due_jobs(pool, limit=limit)
    for job in claimed_jobs:
        await _run_job(pool, app_config, job)
    return claimed_jobs


async def _run_job(pool: asyncpg.Pool, app_config: Config, job: JobRecord) -> None:
    tenant_id = str(job.payload.get("tenant_id", "unknown"))
    started = datetime.now(UTC)
    try:
        if job.job_type == "lead_extraction":
            await _handle_lead_extraction(pool, app_config, job)
        elif job.job_type == "visitor_memory":
            await _handle_visitor_memory(pool, app_config, job)
        elif job.job_type == "handoff_dispatch":
            await _handle_handoff_dispatch(pool, job)
        elif job.job_type == "lead_webhook":
            await _handle_lead_webhook(pool, job)
        elif job.job_type == "knowledge_rebuild":
            await _handle_knowledge_rebuild(pool, job)
        else:
            raise RuntimeError(f"Unknown job type: {job.job_type}")
    except Exception as exc:
        JOB_OUTCOMES.labels(
            tenant_id=tenant_id,
            job_type=job.job_type,
            status=JobStatus.FAILED.value,
        ).inc()
        await mark_job_failed(pool, job, str(exc))
        logger.exception("Job %s failed", job.id)
        return

    JOB_DURATION.labels(tenant_id=tenant_id, job_type=job.job_type).observe(
        (datetime.now(UTC) - started).total_seconds()
    )
    JOB_OUTCOMES.labels(
        tenant_id=tenant_id,
        job_type=job.job_type,
        status=JobStatus.SUCCEEDED.value,
    ).inc()
    await mark_job_succeeded(pool, job.id)


async def _handle_lead_extraction(pool: asyncpg.Pool, app_config: Config, job: JobRecord) -> None:
    from voxagent.leads import extract_lead

    tenant_id = uuid.UUID(str(job.payload["tenant_id"]))
    conversation_id = uuid.UUID(str(job.payload["conversation_id"]))
    conversation = await get_conversation(pool, conversation_id)
    events = await list_conversation_events(pool, conversation_id)
    tenant = await get_tenant(pool, tenant_id)
    if conversation is None or tenant is None:
        raise RuntimeError("Conversation or tenant missing")

    lead = await extract_lead(
        transcript=None,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        llm_config=tenant.llm,
        app_config=app_config,
        pool=pool,
        events=events,
    )
    if lead is not None and tenant.webhook_url:
        await enqueue_job(
            pool,
            JobRecord(
                job_type="lead_webhook",
                payload={
                    "tenant_id": str(tenant_id),
                    "lead_id": str(lead.id),
                },
                idempotency_key=f"lead_webhook:{lead.id}",
            ),
        )


async def _handle_visitor_memory(pool: asyncpg.Pool, app_config: Config, job: JobRecord) -> None:
    from voxagent.memory import summarize_for_memory

    tenant_id = uuid.UUID(str(job.payload["tenant_id"]))
    conversation_id = uuid.UUID(str(job.payload["conversation_id"]))
    visitor_id = str(job.payload["visitor_id"])
    conversation = await get_conversation(pool, conversation_id)
    events = await list_conversation_events(pool, conversation_id)
    tenant = await get_tenant(pool, tenant_id)
    if conversation is None or tenant is None:
        raise RuntimeError("Conversation or tenant missing")

    previous_memory = await get_visitor_memory(pool, tenant_id, visitor_id)
    new_summary = await summarize_for_memory(
        transcript=None,
        previous_summary=previous_memory.summary if previous_memory else None,
        llm_config=tenant.llm,
        app_config=app_config,
        events=events,
    )
    turn_count = (
        previous_memory.turn_count if previous_memory else 0
    ) + len(conversation.transcript)
    await upsert_visitor_memory(
        pool,
        VisitorMemory(
            tenant_id=tenant_id,
            visitor_id=visitor_id,
            summary=new_summary,
            turn_count=turn_count,
        ),
    )


async def _handle_handoff_dispatch(pool: asyncpg.Pool, job: JobRecord) -> None:
    tenant_id = uuid.UUID(str(job.payload["tenant_id"]))
    conversation_id = uuid.UUID(str(job.payload["conversation_id"]))
    conversation = await get_conversation(pool, conversation_id)
    events = await list_conversation_events(pool, conversation_id)
    tenant = await get_tenant(pool, tenant_id)
    if conversation is None or tenant is None or tenant.webhook_url is None:
        return

    detector = HandoffDetector()
    reason = detector.check(events=events)
    if reason is None:
        return

    await fire_handoff_webhook(
        webhook_url=tenant.webhook_url,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        reason=reason,
        transcript=conversation.transcript,
    )


async def _handle_lead_webhook(pool: asyncpg.Pool, job: JobRecord) -> None:
    from voxagent.webhooks import dispatch_lead_webhook

    tenant_id = uuid.UUID(str(job.payload["tenant_id"]))
    lead_id = uuid.UUID(str(job.payload["lead_id"]))
    tenant = await get_tenant(pool, tenant_id)
    lead = await get_lead(pool, lead_id)
    if tenant is None or lead is None or tenant.webhook_url is None:
        return
    await dispatch_lead_webhook(tenant.webhook_url, lead)


async def _handle_knowledge_rebuild(pool: asyncpg.Pool, job: JobRecord) -> None:
    tenant_id = uuid.UUID(str(job.payload["tenant_id"]))
    await rebuild_index(pool, tenant_id)
