from __future__ import annotations

import json
import logging
import uuid

import httpx

from voxagent.config import Config
from voxagent.models import ConversationEvent, LLMConfig, LLMProvider, LeadRecord
from voxagent.queries import create_lead

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
You are a lead-extraction assistant. Analyse the conversation transcript below and \
extract contact information and intent if any is present.

Return ONLY a JSON object with these keys (use null for missing fields):
{
  "name":    "<full name of the user, or null>",
  "email":   "<email address, or null>",
  "phone":   "<phone number, or null>",
  "intent":  "<one-line summary of what the user wanted, or null>",
  "summary": "<2-3 sentence summary of the conversation, or null>"
}

Rules:
- Output raw JSON only — no markdown, no explanation.
- If no name, email, or phone is present, still return the object with those fields set to null.
- Preserve the user's exact email/phone as stated.

Transcript:
"""


def _format_transcript(transcript: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for turn in transcript:
        role = turn.get("role", "unknown").capitalize()
        content = turn.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def transcript_from_events(events: list[ConversationEvent]) -> list[dict[str, str]]:
    ordered = sorted(events, key=lambda event: (event.sequence_number, event.created_at))
    return [{"role": event.role, "content": event.content} for event in ordered]


def _parse_llm_json(raw: str) -> dict[str, str | None]:
    """Extract the JSON object from the LLM response, stripping any surrounding text."""
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        msg = f"No JSON object found in LLM response: {raw!r}"
        raise ValueError(msg)
    return json.loads(raw[start:end])


async def _call_ollama(
    base_url: str,
    model: str,
    prompt: str,
    transcript_text: str,
    client: httpx.AsyncClient,
) -> str:
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript_text},
        ],
    }
    response = await client.post(
        f"{base_url}/api/chat",
        json=payload,
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    return data["message"]["content"]


async def _call_openai(
    api_key: str,
    model: str,
    prompt: str,
    transcript_text: str,
    client: httpx.AsyncClient,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript_text},
        ],
        "temperature": 0.0,
    }
    response = await client.post(
        "https://api.openai.com/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


async def extract_lead(
    transcript: list[dict[str, str]] | None,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    llm_config: LLMConfig,
    app_config: Config,
    pool: "asyncpg.Pool",  # type: ignore[name-defined]  # noqa: F821
    *,
    events: list[ConversationEvent] | None = None,
) -> LeadRecord | None:
    """Run LLM-based lead extraction on a conversation transcript.

    Returns a persisted LeadRecord if at least one of name/email/phone is
    present, or None when the conversation contains no lead information.
    """
    normalized_transcript = transcript or transcript_from_events(events or [])
    if not normalized_transcript:
        return None

    transcript_text = _format_transcript(normalized_transcript)
    prompt = _EXTRACTION_PROMPT

    async with httpx.AsyncClient() as client:
        if llm_config.provider == LLMProvider.OLLAMA:
            base_url = llm_config.base_url or app_config.ollama_base_url
            raw = await _call_ollama(base_url, llm_config.model, prompt, transcript_text, client)
        elif llm_config.provider == LLMProvider.OPENAI:
            if app_config.openai_api_key is None:
                msg = "OPENAI_API_KEY is not configured"
                raise RuntimeError(msg)
            raw = await _call_openai(
                app_config.openai_api_key,
                llm_config.model,
                prompt,
                transcript_text,
                client,
            )
        else:
            msg = f"Unsupported LLM provider for lead extraction: {llm_config.provider}"
            raise ValueError(msg)

    try:
        extracted = _parse_llm_json(raw)
    except (ValueError, json.JSONDecodeError):
        logger.exception("Failed to parse lead extraction response: %r", raw)
        return None

    name: str | None = extracted.get("name") or None
    email: str | None = extracted.get("email") or None
    phone: str | None = extracted.get("phone") or None

    if name is None and email is None and phone is None:
        return None

    intent: str | None = extracted.get("intent") or None
    summary: str | None = extracted.get("summary") or None

    lead = LeadRecord(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        name=name,
        email=email,
        phone=phone,
        intent=intent,
        summary=summary,
    )
    return await create_lead(pool, lead)
