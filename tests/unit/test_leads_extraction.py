from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voxagent.leads import _format_transcript, _parse_llm_json


class TestFormatTranscript:
    def test_multiple_turns(self) -> None:
        transcript = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        result = _format_transcript(transcript)
        assert result == "User: Hi\nAssistant: Hello!"

    def test_empty_transcript(self) -> None:
        assert _format_transcript([]) == ""

    def test_missing_role_defaults_to_unknown(self) -> None:
        result = _format_transcript([{"content": "test"}])
        assert result == "Unknown: test"

    def test_missing_content_defaults_to_empty(self) -> None:
        result = _format_transcript([{"role": "user"}])
        assert result == "User: "


class TestParseLlmJson:
    def test_clean_json(self) -> None:
        raw = '{"name": "Alice", "email": "a@b.com"}'
        result = _parse_llm_json(raw)
        assert result["name"] == "Alice"

    def test_surrounding_text(self) -> None:
        raw = 'Here is the result: {"name": "Bob"} hope that helps'
        result = _parse_llm_json(raw)
        assert result["name"] == "Bob"

    def test_no_json_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="No JSON object found"):
            _parse_llm_json("no json here")


class TestCallOllama:
    @pytest.mark.asyncio
    async def test_payload_and_return(self) -> None:
        from voxagent.leads import _call_ollama

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": '{"name": "test"}'}}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        result = await _call_ollama("http://localhost:11434", "llama3.1", "prompt", "text", mock_client)
        assert result == '{"name": "test"}'
        call_kwargs = mock_client.post.call_args
        assert "/api/chat" in call_kwargs[0][0]

    @pytest.mark.asyncio
    async def test_http_error_propagates(self) -> None:
        import httpx

        from voxagent.leads import _call_ollama

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            await _call_ollama("http://localhost:11434", "model", "p", "t", mock_client)


class TestCallOpenai:
    @pytest.mark.asyncio
    async def test_payload_and_return(self) -> None:
        from voxagent.leads import _call_openai

        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": '{"email": "a@b.com"}'}}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        result = await _call_openai("sk-key", "gpt-4.1", "prompt", "text", mock_client)
        assert result == '{"email": "a@b.com"}'
        call_kwargs = mock_client.post.call_args
        assert "openai.com" in call_kwargs[0][0]
        assert "Bearer sk-key" in str(call_kwargs[1].get("headers", {}))


class TestExtractLead:
    @pytest.mark.asyncio
    async def test_empty_transcript_returns_none(self) -> None:
        from voxagent.leads import extract_lead

        result = await extract_lead([], uuid.uuid4(), uuid.uuid4(), MagicMock(), MagicMock(), MagicMock())
        assert result is None

    @pytest.mark.asyncio
    @patch("voxagent.leads.create_lead", new_callable=AsyncMock)
    @patch("voxagent.leads.httpx.AsyncClient")
    async def test_ollama_saves_lead(self, mock_client_cls: MagicMock, mock_create: AsyncMock) -> None:
        from voxagent.leads import extract_lead
        from voxagent.models import LLMConfig, LLMProvider

        llm_response = json.dumps({"name": "Alice", "email": "a@b.com", "phone": None, "intent": "buy", "summary": "wants to buy"})
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": llm_response}}
        mock_response.raise_for_status = MagicMock()

        mock_instance = AsyncMock()
        mock_instance.post.return_value = mock_response
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        mock_create.return_value = MagicMock()

        app_config = MagicMock()
        app_config.ollama_base_url = "http://localhost:11434"

        llm_config = LLMConfig(provider=LLMProvider.OLLAMA, model="llama3.1")
        transcript = [{"role": "user", "content": "I'm Alice, a@b.com"}]

        await extract_lead(transcript, uuid.uuid4(), uuid.uuid4(), llm_config, app_config, MagicMock())
        mock_create.assert_called_once()
        lead_arg = mock_create.call_args[0][1]
        assert lead_arg.name == "Alice"
        assert lead_arg.email == "a@b.com"

    @pytest.mark.asyncio
    async def test_missing_openai_key_raises(self) -> None:
        from voxagent.leads import extract_lead
        from voxagent.models import LLMConfig, LLMProvider

        app_config = MagicMock()
        app_config.openai_api_key = None
        llm_config = LLMConfig(provider=LLMProvider.OPENAI)
        transcript = [{"role": "user", "content": "Hi"}]

        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            await extract_lead(transcript, uuid.uuid4(), uuid.uuid4(), llm_config, app_config, MagicMock())

    @pytest.mark.asyncio
    async def test_unsupported_provider_raises(self) -> None:
        from voxagent.leads import extract_lead
        from voxagent.models import LLMConfig, LLMProvider

        llm_config = LLMConfig(provider=LLMProvider.OLLAMA)
        llm_config.provider = "unsupported"  # type: ignore[assignment]
        transcript = [{"role": "user", "content": "Hi"}]

        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            await extract_lead(transcript, uuid.uuid4(), uuid.uuid4(), llm_config, MagicMock(), MagicMock())

    @pytest.mark.asyncio
    @patch("voxagent.leads.httpx.AsyncClient")
    async def test_no_contact_info_returns_none(self, mock_client_cls: MagicMock) -> None:
        from voxagent.leads import extract_lead
        from voxagent.models import LLMConfig, LLMProvider

        llm_response = json.dumps({"name": None, "email": None, "phone": None, "intent": "chat", "summary": "small talk"})
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": llm_response}}
        mock_response.raise_for_status = MagicMock()

        mock_instance = AsyncMock()
        mock_instance.post.return_value = mock_response
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        app_config = MagicMock()
        app_config.ollama_base_url = "http://localhost:11434"

        llm_config = LLMConfig(provider=LLMProvider.OLLAMA, model="llama3.1")
        transcript = [{"role": "user", "content": "hello"}]

        result = await extract_lead(transcript, uuid.uuid4(), uuid.uuid4(), llm_config, app_config, MagicMock())
        assert result is None

    @pytest.mark.asyncio
    @patch("voxagent.leads.httpx.AsyncClient")
    async def test_parse_failure_returns_none(self, mock_client_cls: MagicMock) -> None:
        from voxagent.leads import extract_lead
        from voxagent.models import LLMConfig, LLMProvider

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "I cannot extract any JSON"}}
        mock_response.raise_for_status = MagicMock()

        mock_instance = AsyncMock()
        mock_instance.post.return_value = mock_response
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        app_config = MagicMock()
        app_config.ollama_base_url = "http://localhost:11434"

        llm_config = LLMConfig(provider=LLMProvider.OLLAMA, model="llama3.1")
        transcript = [{"role": "user", "content": "hello"}]

        result = await extract_lead(transcript, uuid.uuid4(), uuid.uuid4(), llm_config, app_config, MagicMock())
        assert result is None
