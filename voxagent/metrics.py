from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

CONVERSATIONS_TOTAL = Counter(
    "voxagent_conversations_total",
    "Total conversations processed",
    ["tenant_id"],
)

CONVERSATION_DURATION = Histogram(
    "voxagent_conversation_duration_seconds",
    "Conversation duration in seconds",
    ["tenant_id"],
    buckets=[10, 30, 60, 120, 300, 600, 1800],
)

LEADS_EXTRACTED = Counter(
    "voxagent_leads_extracted_total",
    "Total leads extracted from conversations",
    ["tenant_id"],
)

ACTIVE_SESSIONS = Gauge(
    "voxagent_active_sessions",
    "Currently active voice sessions",
    ["tenant_id"],
)

LLM_REQUESTS = Counter(
    "voxagent_llm_requests_total",
    "Total LLM API requests",
    ["tenant_id", "provider"],
)

LLM_LATENCY = Histogram(
    "voxagent_llm_latency_seconds",
    "LLM request latency",
    ["tenant_id", "provider"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

STT_REQUESTS = Counter(
    "voxagent_stt_requests_total",
    "Total STT requests",
    ["tenant_id", "provider"],
)

TTS_REQUESTS = Counter(
    "voxagent_tts_requests_total",
    "Total TTS requests",
    ["tenant_id", "provider"],
)

HANDOFF_TRIGGERS = Counter(
    "voxagent_handoff_triggers_total",
    "Total handoff triggers",
    ["tenant_id", "reason"],
)

POST_SESSION_STAGE_DURATION = Histogram(
    "voxagent_post_session_stage_duration_seconds",
    "Time spent in synchronous post-session stages before async offload",
    ["tenant_id", "stage", "outcome"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

POST_SESSION_STAGE_FAILURES = Counter(
    "voxagent_post_session_stage_failures_total",
    "Failures observed in synchronous post-session stages",
    ["tenant_id", "stage"],
)

JOB_OUTCOMES = Counter(
    "voxagent_job_outcomes_total",
    "Async job outcomes by tenant and job type",
    ["tenant_id", "job_type", "status"],
)

JOB_DURATION = Histogram(
    "voxagent_job_duration_seconds",
    "Async job execution latency",
    ["tenant_id", "job_type"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)


def metrics_response() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST
