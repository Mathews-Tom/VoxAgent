from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from livekit import agents
from livekit.agents import WorkerOptions, cli

from voxagent.agent.core import VoxAgent
from voxagent.config import load_config
from voxagent.db import close_pool, init_pool
from voxagent.knowledge.engine import KnowledgeEngine
from voxagent.queries import get_tenant


async def entrypoint(ctx: agents.JobContext) -> None:
    app_config = load_config()

    # Extract tenant_id from room name (format: {tenant_id}_{visitor_id})
    room_name = ctx.room.name
    parts = room_name.rsplit("_", 1)
    tenant_id_str = parts[0] if len(parts) == 2 else room_name

    # Load tenant config from database
    pool = await init_pool(app_config.database_url)
    try:
        tenant_config = await get_tenant(pool, uuid.UUID(tenant_id_str))
        if tenant_config is None:
            msg = f"Tenant {tenant_id_str} not found"
            raise RuntimeError(msg)

        # Optionally load knowledge engine for this tenant
        knowledge_engine = None
        knowledge_dir = f"data/{tenant_config.id}/knowledge"
        if Path(knowledge_dir).exists():
            knowledge_engine = KnowledgeEngine(knowledge_dir)
            knowledge_engine.load_index()

        agent = VoxAgent(
            tenant_config=tenant_config,
            app_config=app_config,
            knowledge_engine=knowledge_engine,
        )

        participant = await ctx.wait_for_participant()
        started_at = datetime.now(UTC)

        session = agent.build_session()
        await agent.start(session=session, room=ctx.room, participant=participant)

        # After session ends, save conversation and extract leads
        visitor_id = participant.identity or str(uuid.uuid4())
        conversation = await agent.save_conversation(
            pool=pool, room_name=room_name, visitor_id=visitor_id, started_at=started_at
        )

        # Lead extraction (import inline to avoid circular deps)
        from voxagent.leads import extract_lead

        await extract_lead(
            transcript=conversation.transcript,
            tenant_id=tenant_config.id,
            conversation_id=conversation.id,
            llm_config=tenant_config.llm,
            app_config=app_config,
            pool=pool,
        )
    finally:
        await close_pool(pool)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
