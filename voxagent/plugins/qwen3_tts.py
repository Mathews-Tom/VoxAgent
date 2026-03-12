from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import numpy as np
from livekit import rtc
from livekit.agents import tts, utils

SAMPLE_RATE = 24000
NUM_CHANNELS = 1


@dataclass
class VoiceCloneConfig:
    audio_path: str
    transcript: str
    _cached_prompt: bytes | None = field(default=None, repr=False)


class Qwen3TTS(tts.TTS):
    def __init__(
        self,
        *,
        voice: str = "default",
        language: str = "en",
        clone_config: VoiceCloneConfig | None = None,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
        self._voice = voice
        self._language = language
        self._clone_config = clone_config
        self._model: object | None = None

    def _ensure_model(self) -> object:
        if self._model is None:
            from qwen_tts import Qwen3TTS as Qwen3TTSModel

            self._model = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS")
        return self._model

    def _get_clone_prompt(self) -> bytes | None:
        if self._clone_config is None:
            return None
        if self._clone_config._cached_prompt is not None:
            return self._clone_config._cached_prompt

        model = self._ensure_model()
        with open(self._clone_config.audio_path, "rb") as f:
            audio_bytes = f.read()

        prompt = model.create_speaker_prompt(  # type: ignore[union-attr]
            audio=audio_bytes,
            transcript=self._clone_config.transcript,
        )
        if isinstance(prompt, np.ndarray):
            prompt = prompt.tobytes()
        self._clone_config._cached_prompt = prompt
        return prompt

    def synthesize(self, text: str) -> tts.ChunkedStream:
        return Qwen3TTSStream(
            tts=self,
            text=text,
            clone_prompt=self._get_clone_prompt(),
            model=self._ensure_model(),
        )


class Qwen3TTSStream(tts.ChunkedStream):
    def __init__(
        self,
        *,
        tts: Qwen3TTS,
        text: str,
        clone_prompt: bytes | None,
        model: object,
    ) -> None:
        super().__init__(tts=tts, input_text=text)
        self._text = text
        self._clone_prompt = clone_prompt
        self._model = model

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()

        def _synthesize() -> np.ndarray:
            return self._model.synthesize(  # type: ignore[union-attr]
                self._text,
                speaker_prompt=self._clone_prompt,
            )

        audio_array = await loop.run_in_executor(None, _synthesize)

        if not isinstance(audio_array, np.ndarray):
            audio_array = np.array(audio_array, dtype=np.float32)

        if audio_array.dtype != np.int16:
            audio_array = (audio_array * 32767).clip(-32768, 32767).astype(np.int16)

        frame = rtc.AudioFrame(
            data=audio_array.tobytes(),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
            samples_per_channel=len(audio_array),
        )

        self._event_ch.send_nowait(
            tts.SynthesizedAudio(
                request_id=utils.shortuuid(),
                frame=frame,
            )
        )
