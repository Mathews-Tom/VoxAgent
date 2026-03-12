from __future__ import annotations

from livekit.agents import tts
from livekit.plugins import cartesia, elevenlabs

from voxagent.config import Config
from voxagent.models import TTSConfig, TTSProvider


def create_tts(tts_config: TTSConfig, app_config: Config) -> tts.TTS:
    if tts_config.provider == TTSProvider.ELEVENLABS:
        return elevenlabs.TTS(
            voice=tts_config.voice,
            api_key=app_config.elevenlabs_api_key,
        )
    if tts_config.provider == TTSProvider.CARTESIA:
        return cartesia.TTS(voice=tts_config.voice)
    if tts_config.provider == TTSProvider.QWEN3:
        raise RuntimeError("Qwen3-TTS plugin not yet implemented — available in Phase 2")
    msg = f"Unknown TTS provider: {tts_config.provider!r}"
    raise RuntimeError(msg)
