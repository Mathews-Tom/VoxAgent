from __future__ import annotations

from livekit.agents import stt
from livekit.plugins import deepgram, openai

from voxagent.config import Config
from voxagent.models import STTConfig, STTProvider


def create_stt(stt_config: STTConfig, app_config: Config) -> stt.STT:
    if stt_config.provider == STTProvider.WHISPER:
        return openai.STT.with_groq(
            model=stt_config.model,
            language=stt_config.language,
        )
    if stt_config.provider == STTProvider.DEEPGRAM:
        return deepgram.STT(language=stt_config.language)
    msg = f"Unknown STT provider: {stt_config.provider!r}"
    raise RuntimeError(msg)
