from __future__ import annotations

from datetime import UTC, datetime
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voxagent.models import LLMConfig, STTConfig, TenantConfig, TTSConfig


def _make_tenant(**overrides: object) -> TenantConfig:
    defaults: dict[str, object] = {
        "name": "Test",
        "domain": "test.com",
        "stt": STTConfig(),
        "llm": LLMConfig(system_prompt="Be helpful."),
        "tts": TTSConfig(),
    }
    defaults.update(overrides)
    return TenantConfig(**defaults)  # type: ignore[arg-type]


@patch("voxagent.agent.core.silero")
@patch("voxagent.agent.core.create_tts")
@patch("voxagent.agent.core.create_llm")
@patch("voxagent.agent.core.create_stt")
class TestVoxAgentInit:
    def test_creates_plugins_from_config(
        self, mock_stt: MagicMock, mock_llm: MagicMock, mock_tts: MagicMock, mock_silero: MagicMock
    ) -> None:
        from voxagent.agent.core import VoxAgent

        tenant = _make_tenant()
        app_config = MagicMock()
        VoxAgent(tenant, app_config)
        mock_stt.assert_called_once_with(tenant.stt, app_config)
        mock_llm.assert_called_once_with(tenant.llm, app_config)
        mock_tts.assert_called_once_with(tenant.tts, app_config)

    def test_initializes_empty_transcript(
        self, mock_stt: MagicMock, mock_llm: MagicMock, mock_tts: MagicMock, mock_silero: MagicMock
    ) -> None:
        from voxagent.agent.core import VoxAgent

        agent = VoxAgent(_make_tenant(), MagicMock())
        assert agent.conversation_events() == []
        assert agent.transcript() == []


@patch("voxagent.agent.core.silero")
@patch("voxagent.agent.core.create_tts")
@patch("voxagent.agent.core.create_llm")
@patch("voxagent.agent.core.create_stt")
class TestBuildSession:
    def test_returns_agent_session(
        self, mock_stt: MagicMock, mock_llm: MagicMock, mock_tts: MagicMock, mock_silero: MagicMock
    ) -> None:
        from voxagent.agent.core import VoxAgent

        with patch("voxagent.agent.core.AgentSession") as mock_session_cls:
            agent = VoxAgent(_make_tenant(), MagicMock())
            session = agent.build_session()
            mock_session_cls.assert_called_once()
            assert session is mock_session_cls.return_value


@patch("voxagent.agent.core.silero")
@patch("voxagent.agent.core.create_tts")
@patch("voxagent.agent.core.create_llm")
@patch("voxagent.agent.core.create_stt")
class TestBuildAgent:
    def test_instructions_contain_language_and_system_prompt(
        self, mock_stt: MagicMock, mock_llm: MagicMock, mock_tts: MagicMock, mock_silero: MagicMock
    ) -> None:
        from voxagent.agent.core import VoxAgent

        with patch("voxagent.agent.core.Agent") as mock_agent_cls:
            agent = VoxAgent(_make_tenant(), MagicMock())
            agent.build_agent()
            call_kwargs = mock_agent_cls.call_args.kwargs
            instructions = call_kwargs["instructions"]
            assert "Detect the language" in instructions
            assert "Be helpful." in instructions

    def test_includes_knowledge_tool_when_engine_present(
        self, mock_stt: MagicMock, mock_llm: MagicMock, mock_tts: MagicMock, mock_silero: MagicMock
    ) -> None:
        from voxagent.agent.core import VoxAgent

        with patch("voxagent.agent.core.Agent") as mock_agent_cls, \
             patch("voxagent.agent.tools.create_knowledge_tool") as mock_kt:
            mock_kt.return_value = MagicMock()
            engine = MagicMock()
            agent = VoxAgent(_make_tenant(), MagicMock(), knowledge_engine=engine)
            agent.build_agent()
            mock_kt.assert_called_once_with(engine)
            tools = mock_agent_cls.call_args.kwargs["tools"]
            assert mock_kt.return_value in tools

    def test_no_tools_when_engine_none(
        self, mock_stt: MagicMock, mock_llm: MagicMock, mock_tts: MagicMock, mock_silero: MagicMock
    ) -> None:
        from voxagent.agent.core import VoxAgent

        with patch("voxagent.agent.core.Agent") as mock_agent_cls:
            agent = VoxAgent(_make_tenant(), MagicMock())
            agent.build_agent()
            tools = mock_agent_cls.call_args.kwargs["tools"]
            assert tools == []

    def test_includes_mcp_tools(
        self, mock_stt: MagicMock, mock_llm: MagicMock, mock_tts: MagicMock, mock_silero: MagicMock
    ) -> None:
        from voxagent.agent.core import VoxAgent

        with patch("voxagent.agent.core.Agent") as mock_agent_cls:
            mcp_tool = MagicMock()
            agent = VoxAgent(_make_tenant(), MagicMock(), mcp_tools=[mcp_tool])
            agent.build_agent()
            tools = mock_agent_cls.call_args.kwargs["tools"]
            assert mcp_tool in tools

    def test_includes_visitor_memory_in_instructions(
        self, mock_stt: MagicMock, mock_llm: MagicMock, mock_tts: MagicMock, mock_silero: MagicMock
    ) -> None:
        from voxagent.agent.core import VoxAgent

        with patch("voxagent.agent.core.Agent") as mock_agent_cls:
            agent = VoxAgent(
                _make_tenant(), MagicMock(), visitor_memory_summary="Returning customer, likes blue."
            )
            agent.build_agent()
            instructions = mock_agent_cls.call_args.kwargs["instructions"]
            assert "Returning customer, likes blue." in instructions
            assert "VISITOR CONTEXT" in instructions


@patch("voxagent.agent.core.silero")
@patch("voxagent.agent.core.create_tts")
@patch("voxagent.agent.core.create_llm")
@patch("voxagent.agent.core.create_stt")
class TestOnMessage:
    def test_appends_to_transcript(
        self, mock_stt: MagicMock, mock_llm: MagicMock, mock_tts: MagicMock, mock_silero: MagicMock
    ) -> None:
        from voxagent.agent.core import VoxAgent

        agent = VoxAgent(_make_tenant(), MagicMock())
        agent.on_message("user", "hello")
        agent.on_message("assistant", "hi")
        transcript = agent.transcript()
        events = agent.conversation_events()
        assert len(events) == 2
        assert transcript[0] == {"role": "user", "content": "hello"}
        assert events[0].sequence_number == 0
        assert events[1].sequence_number == 1


@patch("voxagent.agent.core.silero")
@patch("voxagent.agent.core.create_tts")
@patch("voxagent.agent.core.create_llm")
@patch("voxagent.agent.core.create_stt")
class TestSaveConversation:
    @pytest.mark.asyncio
    @patch("voxagent.agent.core.create_conversation", new_callable=AsyncMock)
    @patch("voxagent.agent.core.create_conversation_events", new_callable=AsyncMock)
    async def test_calls_create_conversation(
        self,
        mock_create_events: AsyncMock,
        mock_create: AsyncMock,
        mock_stt: MagicMock,
        mock_llm: MagicMock,
        mock_tts: MagicMock,
        mock_silero: MagicMock,
    ) -> None:
        from voxagent.agent.core import VoxAgent

        mock_create.return_value = MagicMock(id=uuid.uuid4())
        agent = VoxAgent(_make_tenant(), MagicMock())
        agent.on_message("user", "test")

        pool = MagicMock()
        started = datetime.now(UTC)
        await agent.save_conversation(pool, "room-1", "visitor-1", started)

        mock_create.assert_called_once()
        mock_create_events.assert_called_once()
        record = mock_create.call_args[0][1]
        assert record.room_name == "room-1"
        assert record.visitor_id == "visitor-1"
        assert record.duration_seconds >= 0
