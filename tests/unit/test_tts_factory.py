from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from voxagent.config import Config
from voxagent.models import TTSConfig, TTSProvider

# Pre-populate sys.modules with mocks for unavailable livekit plugins
# so that `voxagent.plugins.tts` can be imported without real dependencies.
_mock_cartesia = MagicMock()
_mock_elevenlabs = MagicMock()
sys.modules.setdefault("livekit.plugins.cartesia", _mock_cartesia)
sys.modules.setdefault("livekit.plugins.elevenlabs", _mock_elevenlabs)

# Now safe to import — Qwen3TTS depends on numpy + livekit.agents.tts
# which should be available. If not, the same pattern applies.
from voxagent.plugins.tts import create_tts  # noqa: E402


@pytest.fixture
def app_config() -> Config:
    with patch.dict("os.environ", {
        "DATABASE_URL": "postgresql://x@localhost/x",
        "LIVEKIT_URL": "ws://localhost:7880",
        "LIVEKIT_API_KEY": "k",
        "LIVEKIT_API_SECRET": "s",
        "SESSION_SECRET": "secret",
        "ELEVENLABS_API_KEY": "el-key-123",
    }):
        return Config()


class TestCreateTTS:
    @patch("voxagent.plugins.tts.elevenlabs")
    def test_elevenlabs_with_api_key(self, mock_el: MagicMock, app_config: Config) -> None:
        cfg = TTSConfig(provider=TTSProvider.ELEVENLABS, voice="Rachel")
        create_tts(cfg, app_config)
        mock_el.TTS.assert_called_once_with(voice="Rachel", api_key="el-key-123")

    @patch("voxagent.plugins.tts.cartesia")
    def test_cartesia_with_voice(self, mock_cart: MagicMock, app_config: Config) -> None:
        cfg = TTSConfig(provider=TTSProvider.CARTESIA, voice="narrator")
        create_tts(cfg, app_config)
        mock_cart.TTS.assert_called_once_with(voice="narrator")

    @patch("voxagent.plugins.tts.Qwen3TTS")
    def test_qwen3_without_clone(self, mock_qwen: MagicMock, app_config: Config) -> None:
        cfg = TTSConfig(provider=TTSProvider.QWEN3, voice="default", language="en")
        create_tts(cfg, app_config)
        mock_qwen.assert_called_once_with(voice="default", language="en", clone_config=None)

    @patch("voxagent.plugins.tts.Qwen3TTS")
    @patch("voxagent.plugins.tts.VoiceCloneConfig")
    def test_qwen3_with_clone_config(
        self, mock_vc: MagicMock, mock_qwen: MagicMock, app_config: Config
    ) -> None:
        cfg = TTSConfig(
            provider=TTSProvider.QWEN3,
            voice="cloned",
            language="zh",
            clone_audio_path="/audio/sample.wav",
            clone_transcript="Hello world",
        )
        create_tts(cfg, app_config)
        mock_vc.assert_called_once_with(audio_path="/audio/sample.wav", transcript="Hello world")
        mock_qwen.assert_called_once_with(
            voice="cloned", language="zh", clone_config=mock_vc.return_value
        )

    @patch("voxagent.plugins.tts.elevenlabs")
    def test_elevenlabs_with_none_api_key(self, mock_el: MagicMock) -> None:
        env = {
            "DATABASE_URL": "postgresql://x@localhost/x",
            "LIVEKIT_URL": "ws://localhost:7880",
            "LIVEKIT_API_KEY": "k",
            "LIVEKIT_API_SECRET": "s",
            "SESSION_SECRET": "secret",
        }
        saved = os.environ.get("ELEVENLABS_API_KEY")
        os.environ.pop("ELEVENLABS_API_KEY", None)
        try:
            with patch.dict("os.environ", env, clear=False):
                cfg_no_key = Config()
        finally:
            if saved is not None:
                os.environ["ELEVENLABS_API_KEY"] = saved

        cfg = TTSConfig(provider=TTSProvider.ELEVENLABS, voice="Rachel")
        create_tts(cfg, cfg_no_key)
        mock_el.TTS.assert_called_once_with(voice="Rachel", api_key=None)

    def test_unknown_provider_raises_runtime_error(self, app_config: Config) -> None:
        cfg = TTSConfig(provider=TTSProvider.QWEN3)
        cfg.provider = "unknown"  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="Unknown TTS provider"):
            create_tts(cfg, app_config)
