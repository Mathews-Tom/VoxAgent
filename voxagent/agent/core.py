from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from collections.abc import Awaitable

import asyncpg
from livekit import rtc
from livekit.agents import Agent, AgentSession, RoomInputOptions, llm
from livekit.plugins import silero

from voxagent.config import Config
from voxagent.metrics import POST_SESSION_STAGE_DURATION, POST_SESSION_STAGE_FAILURES
from voxagent.models import ConversationEvent, ConversationRecord, TenantConfig
from voxagent.plugins.llm import create_llm
from voxagent.plugins.stt import create_stt
from voxagent.plugins.tts import create_tts
from voxagent.queries import create_conversation, create_conversation_events

if TYPE_CHECKING:
    from voxagent.knowledge.engine import KnowledgeEngine


_LANGUAGE_INSTRUCTION = (
    "IMPORTANT: Detect the language the user is speaking and always respond "
    "in the same language. If the user switches languages mid-conversation, "
    "switch to match them. If the user mixes languages (e.g., Hindi and English), "
    "respond in the same mixed style."
)


class VoxAgent:
    def __init__(
        self,
        tenant_config: TenantConfig,
        app_config: Config,
        knowledge_engine: KnowledgeEngine | None = None,
        visitor_memory_summary: str | None = None,
        mcp_tools: list[llm.FunctionTool] | None = None,
    ) -> None:
        self._tenant_config = tenant_config
        self._knowledge_engine = knowledge_engine
        self._visitor_memory_summary = visitor_memory_summary
        self._mcp_tools = mcp_tools or []
        self._stt = create_stt(tenant_config.stt, app_config)
        self._llm = create_llm(tenant_config.llm, app_config)
        self._tts = create_tts(tenant_config.tts, app_config)
        self._vad = silero.VAD.load()
        self._events: list[ConversationEvent] = []

    def build_session(self) -> AgentSession:
        return AgentSession(
            stt=self._stt,
            llm=self._llm,
            tts=self._tts,
            vad=self._vad,
        )

    def build_agent(self) -> Agent:
        tools: list[llm.FunctionTool] = []
        if self._knowledge_engine is not None:
            from voxagent.agent.tools import create_knowledge_tool

            tools.append(create_knowledge_tool(self._knowledge_engine))

        tools.extend(self._mcp_tools)

        parts = [_LANGUAGE_INSTRUCTION]
        if self._visitor_memory_summary:
            parts.append(
                f"VISITOR CONTEXT (from previous conversations):\n{self._visitor_memory_summary}"
            )
        parts.append(self._tenant_config.llm.system_prompt)
        instructions = "\n\n".join(parts)

        return Agent(
            instructions=instructions,
            tools=tools,
        )

    def on_message(self, role: str, content: str) -> None:
        self._events.append(
            ConversationEvent(
                role=role,
                content=content,
                sequence_number=len(self._events),
            )
        )

    def on_user_transcript(self, content: str, source: str = "session") -> None:
        self._events.append(
            ConversationEvent(
                role="user",
                content=content,
                source=source,
                sequence_number=len(self._events),
            )
        )

    def on_agent_transcript(self, content: str, source: str = "session") -> None:
        self._events.append(
            ConversationEvent(
                role="assistant",
                content=content,
                source=source,
                sequence_number=len(self._events),
            )
        )

    def conversation_events(self) -> list[ConversationEvent]:
        return list(self._events)

    def transcript(self) -> list[dict[str, str]]:
        return [{"role": event.role, "content": event.content} for event in self._events]

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
            transcript=self.transcript(),
            duration_seconds=duration_seconds,
            started_at=started_at,
            ended_at=ended_at,
        )
        conversation = await create_conversation(pool, record)
        persisted_events = [
            ConversationEvent(
                conversation_id=conversation.id,
                role=event.role,
                content=event.content,
                source=event.source,
                sequence_number=event.sequence_number,
                created_at=event.created_at,
            )
            for event in self._events
        ]
        await create_conversation_events(pool, conversation.id, persisted_events)
        return conversation

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


class PostSessionStageRecorder:
    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    async def run(self, stage: str, action: Awaitable[object]) -> object:
        started = datetime.now(UTC)
        try:
            result = await action
        except Exception:
            duration = (datetime.now(UTC) - started).total_seconds()
            POST_SESSION_STAGE_DURATION.labels(
                tenant_id=self._tenant_id,
                stage=stage,
                outcome="failure",
            ).observe(duration)
            POST_SESSION_STAGE_FAILURES.labels(
                tenant_id=self._tenant_id,
                stage=stage,
            ).inc()
            raise

        duration = (datetime.now(UTC) - started).total_seconds()
        POST_SESSION_STAGE_DURATION.labels(
            tenant_id=self._tenant_id,
            stage=stage,
            outcome="success",
        ).observe(duration)
        return result
