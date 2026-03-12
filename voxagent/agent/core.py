from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import asyncpg
from livekit import rtc
from livekit.agents import Agent, AgentSession, RoomInputOptions
from livekit.plugins import silero

from voxagent.config import Config
from voxagent.models import ConversationRecord, TenantConfig
from voxagent.plugins.llm import create_llm
from voxagent.plugins.stt import create_stt
from voxagent.plugins.tts import create_tts
from voxagent.queries import create_conversation

if TYPE_CHECKING:
    from voxagent.knowledge.engine import KnowledgeEngine


class VoxAgent:
    def __init__(
        self,
        tenant_config: TenantConfig,
        app_config: Config,
        knowledge_engine: KnowledgeEngine | None = None,
    ) -> None:
        self._tenant_config = tenant_config
        self._knowledge_engine = knowledge_engine
        self._stt = create_stt(tenant_config.stt, app_config)
        self._llm = create_llm(tenant_config.llm, app_config)
        self._tts = create_tts(tenant_config.tts, app_config)
        self._vad = silero.VAD.load()
        self._transcript: list[dict[str, str]] = []

    def build_session(self) -> AgentSession:
        return AgentSession(
            stt=self._stt,
            llm=self._llm,
            tts=self._tts,
            vad=self._vad,
        )

    def build_agent(self) -> Agent:
        tools = []
        if self._knowledge_engine is not None:
            from voxagent.agent.tools import create_knowledge_tool

            tools.append(create_knowledge_tool(self._knowledge_engine))

        return Agent(
            instructions=self._tenant_config.llm.system_prompt,
            tools=tools,
        )

    def on_message(self, role: str, content: str) -> None:
        self._transcript.append({"role": role, "content": content})

    async def save_conversation(
        self,
        pool: asyncpg.Pool,
        room_name: str,
        visitor_id: str,
        started_at: datetime,
    ) -> ConversationRecord:
        ended_at = datetime.now(UTC)
        duration_seconds = (ended_at - started_at).total_seconds()
        record = ConversationRecord(
            tenant_id=self._tenant_config.id,
            visitor_id=visitor_id,
            room_name=room_name,
            transcript=self._transcript,
            duration_seconds=duration_seconds,
            started_at=started_at,
            ended_at=ended_at,
        )
        return await create_conversation(pool, record)

    async def start(
        self,
        session: AgentSession,
        room: rtc.Room,
        participant: rtc.RemoteParticipant,
    ) -> None:
        agent = self.build_agent()
        await session.start(
            agent=agent,
            room=room,
            participant=participant,
            room_input_options=RoomInputOptions(),
        )
