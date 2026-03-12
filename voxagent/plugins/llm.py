from __future__ import annotations

from livekit.agents import llm
from livekit.plugins import openai

from voxagent.config import Config
from voxagent.models import LLMConfig, LLMProvider


def create_llm(llm_config: LLMConfig, app_config: Config) -> llm.LLM:
    if llm_config.provider == LLMProvider.OLLAMA:
        return openai.LLM.with_ollama(
            model=llm_config.model,
            base_url=app_config.ollama_base_url,
            temperature=llm_config.temperature,
        )
    if llm_config.provider == LLMProvider.OPENAI:
        return openai.LLM(
            model=llm_config.model,
            temperature=llm_config.temperature,
        )
    msg = f"Unknown LLM provider: {llm_config.provider!r}"
    raise RuntimeError(msg)
