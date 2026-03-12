from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from livekit import rtc
from livekit.agents import tts

_SAMPLE_RATE = 24_000
_NUM_CHANNELS = 1
_MODEL_ID = "Qwen/Qwen3-TTS"


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
            sample_rate=_SAMPLE_RATE,
            num_channels=_NUM_CHANNELS,
        )
        self._voice = voice
        self._language = language
        self._clone_config = clone_config
        self._model: object | None = None

    def _ensure_model_loaded(self) -> object:
        if self._model is None:
            from qwen_tts import Qwen3TTS as Qwen3TTSModel  # type: ignore[import-untyped]

            self._model = Qwen3TTSModel.from_pretrained(_MODEL_ID)
        return self._model

    def _get_clone_prompt(self) -> bytes | None:
        if self._clone_config is None:
            return None

        if self._clone_config._cached_prompt is not None:
            return self._clone_config._cached_prompt

        model = self._ensure_model_loaded()
        audio_bytes = Path(self._clone_config.audio_path).read_bytes()
        prompt: object = model.create_speaker_prompt(  # type: ignore[union-attr]
            audio=audio_bytes,
            transcript=self._clone_config.transcript,
        )
        if isinstance(prompt, np.ndarray):
            prompt = prompt.tobytes()
        assert isinstance(prompt, bytes)  # noqa: S101
        self._clone_config._cached_prompt = prompt
        return prompt

    def synthesize(self, text: str) -> tts.ChunkedStream:
        return Qwen3TTSStream(tts_instance=self, input_text=text)


class Qwen3TTSStream(tts.ChunkedStream):
    def __init__(self, *, tts_instance: Qwen3TTS, input_text: str) -> None:
        super().__init__(tts=tts_instance, input_text=input_text)
        self._qwen_tts = tts_instance

    async def _run(self) -> None:
        model = self._qwen_tts._ensure_model_loaded()
        clone_prompt = self._qwen_tts._get_clone_prompt()
        text = self._input_text

        loop = asyncio.get_running_loop()

        def _synthesize() -> np.ndarray:
            result = model.synthesize(text, speaker_prompt=clone_prompt)  # type: ignore[union-attr]
            if not isinstance(result, np.ndarray):
                return np.array(result, dtype=np.float32)
            return result

        audio_array: np.ndarray = await loop.run_in_executor(None, _synthesize)

        samples_i16: np.ndarray = (
            audio_array.astype(np.float32).clip(-1.0, 1.0) * 32767.0
        ).astype(np.int16)

        frame = rtc.AudioFrame(
            data=samples_i16.tobytes(),
            sample_rate=_SAMPLE_RATE,
            num_channels=_NUM_CHANNELS,
            samples_per_channel=len(samples_i16),
        )
        self._event_ch.send_nowait(
            tts.SynthesizedAudio(
                request_id=self._request_id,
                segment_id=self._segment_id,
                frame=frame,
            )
        )
