from __future__ import annotations

from livekit import agents
from livekit.agents import WorkerOptions, cli

from voxagent.agent.core import VoxAgent
from voxagent.config import load_config
from voxagent.models import TenantConfig


async def entrypoint(ctx: agents.JobContext) -> None:
    app_config = load_config()

    tenant_config = TenantConfig(
        name="default",
        domain="localhost",
    )

    agent = VoxAgent(tenant_config=tenant_config, app_config=app_config)

    participant = await ctx.wait_for_participant()

    session = agent.build_session()
    await agent.start(session=session, room=ctx.room, participant=participant)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
