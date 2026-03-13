from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

import httpx
from livekit import rtc

from voxagent.models import ConversationEvent


_HANDOFF_PHRASES = {
    "talk to a human",
    "speak to a human",
    "speak to an agent",
    "talk to an agent",
    "transfer me",
    "human agent",
    "real person",
    "speak to someone",
    "talk to someone",
    "connect me to a person",
    "let me speak to a representative",
    "i want to speak to a manager",
}


class HandoffReason(StrEnum):
    EXPLICIT_REQUEST = "explicit_request"
    REPEATED_FAILURE = "repeated_failure"
    KEYWORD_MATCH = "keyword_match"


class HandoffDetector:
    def __init__(
        self,
        keywords: list[str] | None = None,
        failure_threshold: int = 3,
    ) -> None:
        self._keywords = [kw.lower() for kw in keywords] if keywords else []
        self._failure_threshold = failure_threshold

    def check(
        self,
        transcript: list[dict[str, str]] | None = None,
        events: list[ConversationEvent] | None = None,
    ) -> HandoffReason | None:
        turns = events_to_transcript(events) if events is not None else (transcript or [])
        user_messages = [m["content"] for m in turns if m.get("role") == "user"]

        if not user_messages:
            return None

        latest = user_messages[-1].lower()

        for phrase in _HANDOFF_PHRASES:
            if phrase in latest:
                return HandoffReason.EXPLICIT_REQUEST

        for keyword in self._keywords:
            if keyword in latest:
                return HandoffReason.KEYWORD_MATCH

        if len(user_messages) >= self._failure_threshold:
            window = user_messages[-5:]
            normalized = [m.lower().strip() for m in window]
            latest_normalized = normalized[-1]
            matches = sum(1 for m in normalized if m == latest_normalized)
            if matches >= self._failure_threshold:
                return HandoffReason.REPEATED_FAILURE

        return None


async def fire_handoff_webhook(
    webhook_url: str,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    reason: HandoffReason,
    transcript: list[dict[str, str]],
) -> None:
    payload = {
        "tenant_id": str(tenant_id),
        "conversation_id": str(conversation_id),
        "reason": str(reason),
        "transcript": transcript,
        "triggered_at": datetime.now(UTC).isoformat(),
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(webhook_url, json=payload)
        response.raise_for_status()


def events_to_transcript(events: list[ConversationEvent] | None) -> list[dict[str, str]]:
    if not events:
        return []
    ordered = sorted(events, key=lambda event: (event.sequence_number, event.created_at))
    return [{"role": event.role, "content": event.content} for event in ordered]


async def mute_bot_on_human_join(room: rtc.Room) -> None:
    @room.on("participant_connected")
    def on_participant_connected(participant: rtc.RemoteParticipant) -> None:
        identity = participant.identity.lower()
        if "agent" not in identity and "human" not in identity:
            return

        local_participant = room.local_participant
        for publication in local_participant.track_publications.values():
            if publication.track and publication.track.kind == rtc.TrackKind.KIND_AUDIO:
                local_participant.set_microphone_enabled(False)
                return
