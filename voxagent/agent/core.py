from __future__ import annotations

from livekit import rtc
from livekit.agents import Agent, AgentSession, RoomInputOptions
from livekit.plugins import silero

from voxagent.config import Config
from voxagent.models import TenantConfig
from voxagent.plugins.llm import create_llm
from voxagent.plugins.stt import create_stt
from voxagent.plugins.tts import create_tts


class VoxAgent:
    def __init__(self, tenant_config: TenantConfig, app_config: Config) -> None:
        self._tenant_config = tenant_config
        self._stt = create_stt(tenant_config.stt, app_config)
        self._llm = create_llm(tenant_config.llm, app_config)
        self._tts = create_tts(tenant_config.tts, app_config)
        self._vad = silero.VAD.load()

    def build_session(self) -> AgentSession:
        return AgentSession(
            stt=self._stt,
            llm=self._llm,
            tts=self._tts,
            vad=self._vad,
        )

    def build_agent(self) -> Agent:
        return Agent(
            instructions=self._tenant_config.llm.system_prompt,
        )

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
