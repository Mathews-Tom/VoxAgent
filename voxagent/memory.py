from __future__ import annotations

import logging

import httpx

from voxagent.config import Config
from voxagent.agent.handoff import events_to_transcript
from voxagent.models import ConversationEvent, LLMConfig, LLMProvider

logger = logging.getLogger(__name__)

_SUMMARIZE_PROMPT = """\
You are a conversation summarizer. Given the previous memory (if any) and the \
new conversation transcript, produce a concise summary that captures:
- Key facts about the visitor (name, preferences, issues mentioned)
- Unresolved questions or pending actions
- Important context for future conversations

Return ONLY a plain-text summary (no JSON, no markdown). Maximum 300 words.
"""


async def summarize_for_memory(
    transcript: list[dict[str, str]] | None,
    previous_summary: str | None,
    llm_config: LLMConfig,
    app_config: Config,
    *,
    events: list[ConversationEvent] | None = None,
) -> str:
    normalized_transcript = transcript or events_to_transcript(events)
    lines: list[str] = []
    if previous_summary:
        lines.append(f"Previous memory:\n{previous_summary}\n")
    lines.append("New conversation:")
    for turn in normalized_transcript:
        role = turn.get("role", "unknown").capitalize()
        content = turn.get("content", "")
        lines.append(f"{role}: {content}")
    user_content = "\n".join(lines)

    async with httpx.AsyncClient() as client:
        if llm_config.provider == LLMProvider.OLLAMA:
            base_url = llm_config.base_url or app_config.ollama_base_url
            response = await client.post(
                f"{base_url}/api/chat",
                json={
                    "model": llm_config.model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": _SUMMARIZE_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                },
                timeout=60.0,
            )
            response.raise_for_status()
            return response.json()["message"]["content"]

        if llm_config.provider == LLMProvider.OPENAI:
            if app_config.openai_api_key is None:
                msg = "OPENAI_API_KEY is not configured"
                raise RuntimeError(msg)
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json={
                    "model": llm_config.model,
                    "messages": [
                        {"role": "system", "content": _SUMMARIZE_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.3,
                },
                headers={"Authorization": f"Bearer {app_config.openai_api_key}"},
                timeout=60.0,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

        msg = f"Unsupported LLM provider for memory summarization: {llm_config.provider}"
        raise ValueError(msg)
