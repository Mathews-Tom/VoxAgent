from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from livekit import agents
from livekit.agents import WorkerOptions, cli

from voxagent.agent.core import PostSessionStageRecorder, VoxAgent
from voxagent.config import load_config
from voxagent.db import close_pool, init_pool
from voxagent.jobs.runner import enqueue_post_session_jobs
from voxagent.knowledge.engine import KnowledgeEngine
from voxagent.queries import get_tenant, get_visitor_memory, upsert_visitor_memory

logger = logging.getLogger(__name__)


async def entrypoint(ctx: agents.JobContext) -> None:
    app_config = load_config()

    # Extract tenant_id from room name (format: {tenant_id}_{visitor_id})
    room_name = ctx.room.name
    parts = room_name.rsplit("_", 1)
    tenant_id_str = parts[0] if len(parts) == 2 else room_name

    pool = await init_pool(app_config.database_url)
    try:
        tenant_config = await get_tenant(pool, uuid.UUID(tenant_id_str))
        if tenant_config is None:
            msg = f"Tenant {tenant_id_str} not found"
            raise RuntimeError(msg)

        # Knowledge engine
        knowledge_engine = None
        knowledge_dir = f"data/{tenant_config.id}/knowledge"
        if Path(knowledge_dir).exists():
            knowledge_engine = KnowledgeEngine(knowledge_dir)
            knowledge_engine.load_index()

        # Visitor memory — retrieve prior context
        participant = await ctx.wait_for_participant()
        visitor_id = participant.identity or str(uuid.uuid4())
        prior_memory = await get_visitor_memory(pool, tenant_config.id, visitor_id)

        # MCP tools — discover and load from tenant-configured servers
        mcp_tools = []
        if tenant_config.mcp_servers:
            from voxagent.agent.mcp import load_mcp_tools

            mcp_tools = await load_mcp_tools(tenant_config.mcp_servers)

        agent = VoxAgent(
            tenant_config=tenant_config,
            app_config=app_config,
            knowledge_engine=knowledge_engine,
            visitor_memory_summary=prior_memory.summary if prior_memory else None,
            mcp_tools=mcp_tools,
        )
        stage_recorder = PostSessionStageRecorder(str(tenant_config.id))

        started_at = datetime.now(UTC)

        session = agent.build_session()
        await agent.start(session=session, room=ctx.room, participant=participant)

        # Post-session: save conversation
        conversation = await stage_recorder.run(
            "conversation_persist",
            agent.save_conversation(
                pool=pool, room_name=room_name, visitor_id=visitor_id, started_at=started_at
            ),
        )

        if app_config.enable_async_post_session_jobs:
            await stage_recorder.run(
                "post_session_enqueue",
                enqueue_post_session_jobs(
                    pool=pool,
                    tenant_id=tenant_config.id,
                    conversation_id=conversation.id,
                    visitor_id=visitor_id,
                ),
            )
            return

        # Lead extraction
        from voxagent.leads import extract_lead

        lead = await stage_recorder.run(
            "lead_extraction",
            extract_lead(
                transcript=conversation.transcript,
                tenant_id=tenant_config.id,
                conversation_id=conversation.id,
                llm_config=tenant_config.llm,
                app_config=app_config,
                pool=pool,
            ),
        )

        # Webhook dispatch for extracted leads
        if lead is not None and tenant_config.webhook_url:
            from voxagent.webhooks import dispatch_lead_webhook

            try:
                await stage_recorder.run(
                    "lead_webhook",
                    dispatch_lead_webhook(tenant_config.webhook_url, lead),
                )
            except Exception:
                logger.exception("Webhook dispatch failed for lead %s", lead.id)

        # Update visitor memory with conversation summary
        from voxagent.memory import summarize_for_memory
        from voxagent.models import VisitorMemory

        try:
            new_summary = await stage_recorder.run(
                "visitor_memory_summary",
                summarize_for_memory(
                    transcript=conversation.transcript,
                    previous_summary=prior_memory.summary if prior_memory else None,
                    llm_config=tenant_config.llm,
                    app_config=app_config,
                ),
            )
            turn_count = (prior_memory.turn_count if prior_memory else 0) + len(
                conversation.transcript
            )
            await stage_recorder.run(
                "visitor_memory_persist",
                upsert_visitor_memory(
                    pool,
                    VisitorMemory(
                        tenant_id=tenant_config.id,
                        visitor_id=visitor_id,
                        summary=new_summary,
                        turn_count=turn_count,
                    ),
                ),
            )
        except Exception:
            logger.exception("Visitor memory update failed for %s", visitor_id)

    finally:
        await close_pool(pool)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
