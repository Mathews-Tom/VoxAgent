from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum


def _utcnow() -> datetime:
    return datetime.now(UTC)

from pydantic import BaseModel, Field


class STTProvider(StrEnum):
    WHISPER = "whisper"
    DEEPGRAM = "deepgram"


class LLMProvider(StrEnum):
    OLLAMA = "ollama"
    OPENAI = "openai"


class TTSProvider(StrEnum):
    QWEN3 = "qwen3"
    ELEVENLABS = "elevenlabs"
    CARTESIA = "cartesia"


class STTConfig(BaseModel):
    provider: STTProvider = STTProvider.WHISPER
    language: str = "en"
    model: str = "large-v3"


class LLMConfig(BaseModel):
    provider: LLMProvider = LLMProvider.OLLAMA
    model: str = "llama3.1"
    base_url: str | None = None
    temperature: float = 0.7
    system_prompt: str = "You are a helpful voice assistant."


class TTSConfig(BaseModel):
    provider: TTSProvider = TTSProvider.QWEN3
    voice: str = "default"
    language: str = "en"
    clone_audio_path: str | None = None
    clone_transcript: str | None = None


class MCPServerConfig(BaseModel):
    name: str
    url: str
    api_key: str | None = None


class TenantConfig(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    domain: str
    password_hash: str | None = None
    stt: STTConfig = Field(default_factory=STTConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    greeting: str = "Hello! How can I help you today?"
    widget_color: str = "#6366f1"
    widget_position: str = "bottom-right"
    allowed_origins: list[str] = Field(default_factory=list)
    webhook_url: str | None = None
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class ConversationRecord(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: uuid.UUID
    visitor_id: str
    room_name: str
    transcript: list[dict[str, str]] = Field(default_factory=list)
    language: str = "en"
    duration_seconds: float = 0.0
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None


class LeadRecord(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    intent: str | None = None
    summary: str | None = None
    extracted_at: datetime = Field(default_factory=_utcnow)


class VisitorMemory(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: uuid.UUID
    visitor_id: str
    summary: str
    turn_count: int = 0
    updated_at: datetime = Field(default_factory=_utcnow)
