from __future__ import annotations

from livekit.agents import tts
from livekit.plugins import cartesia, elevenlabs

from voxagent.config import Config
from voxagent.models import TTSConfig, TTSProvider
from voxagent.plugins.qwen3_tts import Qwen3TTS, VoiceCloneConfig


def create_tts(tts_config: TTSConfig, app_config: Config) -> tts.TTS:
    if tts_config.provider == TTSProvider.ELEVENLABS:
        return elevenlabs.TTS(
            voice=tts_config.voice,
            api_key=app_config.elevenlabs_api_key,
        )
    if tts_config.provider == TTSProvider.CARTESIA:
        return cartesia.TTS(voice=tts_config.voice)
    if tts_config.provider == TTSProvider.QWEN3:
        clone_config: VoiceCloneConfig | None = None
        if tts_config.clone_audio_path and tts_config.clone_transcript:
            clone_config = VoiceCloneConfig(
                audio_path=tts_config.clone_audio_path,
                transcript=tts_config.clone_transcript,
            )
        return Qwen3TTS(
            voice=tts_config.voice,
            language=tts_config.language,
            clone_config=clone_config,
        )
    msg = f"Unknown TTS provider: {tts_config.provider!r}"
    raise RuntimeError(msg)
