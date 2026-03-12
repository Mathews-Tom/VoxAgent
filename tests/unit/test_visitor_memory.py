from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voxagent.models import LLMConfig, LLMProvider, VisitorMemory
from voxagent.queries import get_visitor_memory, upsert_visitor_memory
from voxagent.memory import summarize_for_memory


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def visitor_id() -> str:
    return "visitor-abc-123"


@pytest.fixture
def mock_pool() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def app_config_obj() -> MagicMock:
    cfg = MagicMock()
    cfg.ollama_base_url = "http://localhost:11434"
    cfg.openai_api_key = "sk-test-key"
    return cfg


@pytest.fixture
def sample_memory_row(tenant_id: uuid.UUID, visitor_id: str) -> dict:
    return {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "visitor_id": visitor_id,
        "summary": "Visitor asked about pricing.",
        "turn_count": 5,
        "updated_at": datetime.now(UTC),
    }


class TestGetVisitorMemory:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(
        self, mock_pool: AsyncMock, tenant_id: uuid.UUID, visitor_id: str
    ) -> None:
        mock_pool.fetchrow = AsyncMock(return_value=None)
        result = await get_visitor_memory(mock_pool, tenant_id, visitor_id)
        assert result is None
        mock_pool.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_visitor_memory_when_found(
        self,
        mock_pool: AsyncMock,
        tenant_id: uuid.UUID,
        visitor_id: str,
        sample_memory_row: dict,
    ) -> None:
        mock_pool.fetchrow = AsyncMock(return_value=sample_memory_row)
        result = await get_visitor_memory(mock_pool, tenant_id, visitor_id)
        assert isinstance(result, VisitorMemory)
        assert result.tenant_id == tenant_id
        assert result.visitor_id == visitor_id
        assert result.summary == "Visitor asked about pricing."
        assert result.turn_count == 5


class TestUpsertVisitorMemory:
    @pytest.mark.asyncio
    async def test_inserts_new_memory(
        self,
        mock_pool: AsyncMock,
        tenant_id: uuid.UUID,
        visitor_id: str,
        sample_memory_row: dict,
    ) -> None:
        mock_pool.fetchrow = AsyncMock(return_value=sample_memory_row)
        memory = VisitorMemory(
            tenant_id=tenant_id,
            visitor_id=visitor_id,
            summary="New visitor summary.",
            turn_count=3,
        )
        result = await upsert_visitor_memory(mock_pool, memory)
        assert isinstance(result, VisitorMemory)
        assert result.tenant_id == tenant_id
        mock_pool.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_existing_memory(
        self,
        mock_pool: AsyncMock,
        tenant_id: uuid.UUID,
        visitor_id: str,
    ) -> None:
        updated_row = {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "visitor_id": visitor_id,
            "summary": "Updated summary after second conversation.",
            "turn_count": 10,
            "updated_at": datetime.now(UTC),
        }
        mock_pool.fetchrow = AsyncMock(return_value=updated_row)
        memory = VisitorMemory(
            tenant_id=tenant_id,
            visitor_id=visitor_id,
            summary="Updated summary after second conversation.",
            turn_count=10,
        )
        result = await upsert_visitor_memory(mock_pool, memory)
        assert result.summary == "Updated summary after second conversation."
        assert result.turn_count == 10


class TestSummarizeForMemory:
    @pytest.mark.asyncio
    async def test_ollama_provider(self, app_config_obj: MagicMock) -> None:
        llm_config = LLMConfig(provider=LLMProvider.OLLAMA, model="llama3.1")
        transcript = [
            {"role": "user", "content": "What is your return policy?"},
            {"role": "assistant", "content": "You can return items within 30 days."},
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "Visitor asked about return policy."}}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voxagent.memory.httpx.AsyncClient", return_value=mock_client):
            result = await summarize_for_memory(transcript, None, llm_config, app_config_obj)

        assert result == "Visitor asked about return policy."
        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.call_args
        assert "/api/chat" in call_kwargs.args[0]

    @pytest.mark.asyncio
    async def test_openai_provider(self, app_config_obj: MagicMock) -> None:
        llm_config = LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4.1")
        transcript = [{"role": "user", "content": "Hello"}]
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Summary via OpenAI."}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voxagent.memory.httpx.AsyncClient", return_value=mock_client):
            result = await summarize_for_memory(transcript, None, llm_config, app_config_obj)

        assert result == "Summary via OpenAI."
        call_kwargs = mock_client.post.call_args
        assert "openai.com" in call_kwargs.args[0]
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer sk-test-key"

    @pytest.mark.asyncio
    async def test_with_previous_summary(self, app_config_obj: MagicMock) -> None:
        llm_config = LLMConfig(provider=LLMProvider.OLLAMA, model="llama3.1")
        transcript = [{"role": "user", "content": "Any updates?"}]
        previous_summary = "Visitor previously asked about shipping."

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "Combined summary."}}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voxagent.memory.httpx.AsyncClient", return_value=mock_client):
            result = await summarize_for_memory(
                transcript, previous_summary, llm_config, app_config_obj
            )

        assert result == "Combined summary."
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs["json"]
        user_msg = payload["messages"][1]["content"]
        assert "Previous memory:" in user_msg
        assert "Visitor previously asked about shipping." in user_msg

    @pytest.mark.asyncio
    async def test_raises_for_unsupported_provider(self, app_config_obj: MagicMock) -> None:
        llm_config = LLMConfig(provider=LLMProvider.OLLAMA, model="llama3.1")
        # Force an unsupported provider value
        object.__setattr__(llm_config, "provider", "unsupported")
        transcript = [{"role": "user", "content": "hi"}]
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            await summarize_for_memory(transcript, None, llm_config, app_config_obj)
