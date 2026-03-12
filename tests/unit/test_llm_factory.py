from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from voxagent.config import Config
from voxagent.models import LLMConfig, LLMProvider


@pytest.fixture
def app_config() -> Config:
    with patch.dict("os.environ", {
        "DATABASE_URL": "postgresql://x@localhost/x",
        "LIVEKIT_URL": "ws://localhost:7880",
        "LIVEKIT_API_KEY": "k",
        "LIVEKIT_API_SECRET": "s",
        "SESSION_SECRET": "secret",
        "OLLAMA_BASE_URL": "http://localhost:11434",
    }):
        return Config()


class TestCreateLLM:
    @patch("voxagent.plugins.llm.openai")
    def test_ollama_calls_with_ollama(self, mock_openai: MagicMock, app_config: Config) -> None:
        from voxagent.plugins.llm import create_llm

        cfg = LLMConfig(provider=LLMProvider.OLLAMA, model="llama3.1", temperature=0.5)
        create_llm(cfg, app_config)
        mock_openai.LLM.with_ollama.assert_called_once_with(
            model="llama3.1",
            base_url="http://localhost:11434",
            temperature=0.5,
        )

    @patch("voxagent.plugins.llm.openai")
    def test_openai_calls_llm(self, mock_openai: MagicMock, app_config: Config) -> None:
        from voxagent.plugins.llm import create_llm

        cfg = LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4.1", temperature=0.3)
        create_llm(cfg, app_config)
        mock_openai.LLM.assert_called_once_with(model="gpt-4.1", temperature=0.3)

    @patch("voxagent.plugins.llm.openai")
    def test_ollama_uses_app_config_base_url(self, mock_openai: MagicMock, app_config: Config) -> None:
        from voxagent.plugins.llm import create_llm

        cfg = LLMConfig(provider=LLMProvider.OLLAMA, model="mistral")
        create_llm(cfg, app_config)
        call_kwargs = mock_openai.LLM.with_ollama.call_args.kwargs
        assert call_kwargs["base_url"] == "http://localhost:11434"

    @patch("voxagent.plugins.llm.openai")
    def test_openai_returns_instance(self, mock_openai: MagicMock, app_config: Config) -> None:
        from voxagent.plugins.llm import create_llm

        sentinel = MagicMock()
        mock_openai.LLM.return_value = sentinel
        cfg = LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4.1")
        result = create_llm(cfg, app_config)
        assert result is sentinel

    def test_unknown_provider_raises_runtime_error(self, app_config: Config) -> None:
        from voxagent.plugins.llm import create_llm

        cfg = LLMConfig(provider=LLMProvider.OLLAMA)
        cfg.provider = "bogus"  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="Unknown LLM provider"):
            create_llm(cfg, app_config)
