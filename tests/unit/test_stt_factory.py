from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from voxagent.config import Config
from voxagent.models import STTConfig, STTProvider


@pytest.fixture
def app_config() -> Config:
    with patch.dict("os.environ", {
        "DATABASE_URL": "postgresql://x@localhost/x",
        "LIVEKIT_URL": "ws://localhost:7880",
        "LIVEKIT_API_KEY": "k",
        "LIVEKIT_API_SECRET": "s",
        "SESSION_SECRET": "secret",
    }):
        return Config()


class TestCreateSTT:
    @patch("voxagent.plugins.stt.openai")
    def test_whisper_calls_with_groq(self, mock_openai: MagicMock, app_config: Config) -> None:
        from voxagent.plugins.stt import create_stt

        cfg = STTConfig(provider=STTProvider.WHISPER, model="large-v3", language="en")
        create_stt(cfg, app_config)
        mock_openai.STT.with_groq.assert_called_once_with(model="large-v3", language="en")

    @patch("voxagent.plugins.stt.deepgram")
    def test_deepgram_calls_stt(self, mock_deepgram: MagicMock, app_config: Config) -> None:
        from voxagent.plugins.stt import create_stt

        cfg = STTConfig(provider=STTProvider.DEEPGRAM, language="fr")
        create_stt(cfg, app_config)
        mock_deepgram.STT.assert_called_once_with(language="fr")

    @patch("voxagent.plugins.stt.openai")
    def test_whisper_custom_model_and_language(self, mock_openai: MagicMock, app_config: Config) -> None:
        from voxagent.plugins.stt import create_stt

        cfg = STTConfig(provider=STTProvider.WHISPER, model="small", language="de")
        create_stt(cfg, app_config)
        mock_openai.STT.with_groq.assert_called_once_with(model="small", language="de")

    def test_unknown_provider_raises_runtime_error(self, app_config: Config) -> None:
        from voxagent.plugins.stt import create_stt

        cfg = STTConfig(provider=STTProvider.WHISPER)
        # Monkey-patch to simulate unknown provider
        cfg.provider = "unknown_provider"  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="Unknown STT provider"):
            create_stt(cfg, app_config)

    @patch("voxagent.plugins.stt.openai")
    def test_whisper_returns_stt_instance(self, mock_openai: MagicMock, app_config: Config) -> None:
        from voxagent.plugins.stt import create_stt

        sentinel = MagicMock()
        mock_openai.STT.with_groq.return_value = sentinel
        cfg = STTConfig(provider=STTProvider.WHISPER)
        result = create_stt(cfg, app_config)
        assert result is sentinel
