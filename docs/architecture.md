# Architecture

VoxAgent is a multi-tenant voice AI platform with two runtimes (Python backend + Node.js widget), one shared database (PostgreSQL), and a real-time voice layer (LiveKit).

## System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser                                                             │
│  ┌────────────────┐                                                  │
│  │  Voice Widget   │ ── WebRTC audio ──→ LiveKit Server              │
│  │  (Next.js)      │ ← WebRTC audio ───┘       │                    │
│  └────────┬───────┘                             │                    │
│           │ REST                                │                    │
│           ▼                                     ▼                    │
│  ┌──────────────────┐                  ┌──────────────────┐          │
│  │  FastAPI Server   │                  │  VoxAgent Worker  │          │
│  │                   │                  │                   │          │
│  │  /api/token       │                  │  STT (Whisper/    │          │
│  │  /api/tenants     │                  │       Deepgram)   │          │
│  │  /dashboard/*     │                  │  LLM (Ollama/     │          │
│  │  /health          │                  │       OpenAI)     │          │
│  │  /metrics         │                  │  TTS (Qwen3/      │          │
│  │                   │                  │       ElevenLabs)  │          │
│  └────────┬──────────┘                  │  VAD (Silero)     │          │
│           │                             │                   │          │
│           │                             │  Knowledge Tool   │          │
│           │                             │  MCP Tools        │          │
│           │                             │  Handoff Detector │          │
│           │                             └────────┬──────────┘          │
│           │                                      │                    │
│           ▼                                      ▼                    │
│  ┌───────────────────────────────────────────────────────────┐       │
│  │  PostgreSQL                                                │       │
│  │  tenants │ conversations │ leads │ visitor_memories         │       │
│  └───────────────────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────────┘
```

## Components

### Voice Agent Worker (`voxagent/main.py`)

The LiveKit agent worker runs as a separate process from the API server. When a visitor connects to a LiveKit room, the worker:

1. Extracts the `tenant_id` from the room name (format: `{tenant_id}_{visitor_id}`)
2. Loads the tenant's configuration from the database
3. Loads the knowledge base index from disk (if available)
4. Retrieves prior visitor memory for context continuity
5. Discovers MCP tools from tenant-configured servers
6. Builds the `VoxAgent` with the tenant's STT/LLM/TTS providers
7. Runs the voice session (STT → LLM → TTS loop)
8. After session ends:
   - Saves the conversation transcript to the database
   - Extracts leads via LLM and persists them
   - Dispatches lead webhook (if configured)
   - Summarizes the conversation and updates visitor memory

### Agent Core (`voxagent/agent/core.py`)

`VoxAgent` is the orchestrator that wires LiveKit's agent framework:

- **VAD**: Silero Voice Activity Detection — detects when the user starts/stops speaking
- **STT**: Speech-to-Text — converts audio to text (Whisper or Deepgram)
- **LLM**: Language Model — generates responses, can call tools (Ollama or OpenAI)
- **TTS**: Text-to-Speech — converts response text to audio (Qwen3, ElevenLabs, or Cartesia)

The LLM receives a system prompt constructed from:
1. Language-matching instruction (respond in the user's language)
2. Visitor memory context (from prior sessions, if available)
3. The tenant's custom system prompt

### Knowledge Engine (`voxagent/knowledge/`)

Hybrid retrieval system combining lexical and semantic search:

```
Query ──→ BM25 (lexical) ──→ Ranked list A ──┐
     └──→ FAISS (semantic) ──→ Ranked list B ──┤
                                                ▼
                                     Reciprocal Rank Fusion (k=60)
                                                │
                                                ▼
                                        Merged ranked results
```

- **BM25** (`rank_bm25`): Token-level matching, good for exact terms
- **FAISS** (`faiss-cpu`): Dense vector similarity via `all-MiniLM-L6-v2` embeddings
- **RRF**: `score = Σ 1/(k + rank)` — chunks appearing in both rankings get boosted
- **Incremental indexing**: SHA-256 content hashes track which pages changed since last crawl

### Handoff Detection (`voxagent/agent/handoff.py`)

Three trigger types for escalation to human agents:

| Trigger | Detection Method |
|---------|-----------------|
| Explicit request | Phrase matching: "talk to a human", "transfer me", etc. |
| Repeated failure | 3+ identical user messages in a 5-message window |
| Keyword match | Tenant-configured custom keywords |

When triggered, a webhook fires with the conversation context.

### MCP Tool Integration (`voxagent/agent/mcp.py`)

Tenants can configure external MCP (Model Context Protocol) servers. At session start:

1. The worker sends `tools/list` (JSON-RPC) to each configured server
2. Discovered tools are registered as `FunctionTool` instances with namespaced names (`mcp_{server}_{tool}`)
3. When the LLM invokes a tool, the worker proxies `tools/call` back to the MCP server

### FastAPI Server (`voxagent/server/`)

The API server handles:

- **Tenant management** — CRUD REST API for creating and configuring tenants
- **Token generation** — Mints LiveKit access tokens for widget connections
- **Dashboard** — HTMX-rendered pages for conversations, leads, analytics, and configuration
- **Lead API** — JSON listing and CSV export of extracted leads
- **Knowledge management** — File upload and website crawl triggers
- **Authentication** — Session-based with signed cookies (24-hour TTL)
- **Rate limiting** — Sliding window: 30 req/min per IP, 100 req/min per tenant
- **Metrics** — Prometheus endpoint at `/metrics`

### Widget (`widget/`)

Next.js application that:

- Fetches tenant config (colors, greeting, position) from the API
- Requests a LiveKit token via `POST /api/token`
- Connects to the LiveKit room and streams audio
- Renders as a floating button with microphone icon

Deployable as a standalone app or embedded via `<script>` tag.

## Data Model

### Tenant Configuration

Each tenant has independent configuration for every component:

```
TenantConfig
├── STTConfig (provider, language, model)
├── LLMConfig (provider, model, base_url, temperature, system_prompt)
├── TTSConfig (provider, voice, language, clone_audio_path)
├── Widget settings (color, position, greeting, allowed_origins)
├── webhook_url (for lead routing)
└── mcp_servers[] (name, url, api_key)
```

### Conversation Flow

```
Widget connects → Room created → Agent joins
    │
    ▼
Voice loop (user speaks → STT → LLM → TTS → user hears)
    │
    ├── LLM may call search_knowledge tool
    ├── LLM may call MCP tools
    └── Handoff detector checks each turn
    │
    ▼
Session ends → Transcript saved
    │
    ├── Lead extraction (LLM parses name/email/phone/intent)
    ├── Webhook dispatch (if configured)
    └── Visitor memory update (LLM summarizes for next session)
```

## Database Schema

Four application tables plus a migration tracker:

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `tenants` | Multi-tenant config | STT/LLM/TTS JSONB, widget settings, webhook_url, mcp_servers |
| `conversations` | Session transcripts | tenant_id, visitor_id, transcript JSONB, duration, timestamps |
| `leads` | Extracted contacts | tenant_id, conversation_id, name, email, phone, intent |
| `visitor_memories` | Cross-session context | tenant_id, visitor_id (UNIQUE), summary, turn_count |

Migrations are plain SQL files in `migrations/`, applied automatically on server startup via `run_migrations()`.

## Observability

### Structured Logging

JSON-formatted logs with `conversation_id` and `tenant_id` correlation via `contextvars`. Configurable via `LOG_LEVEL`.

### Prometheus Metrics

9 metrics exposed at `/metrics`:

- Conversation counters and duration histogram
- Lead extraction counter
- Active session gauge
- LLM/STT/TTS request counters and latency histograms
- Handoff trigger counter (by reason)

### Health Check

`GET /health` returns `{"status": "ok"}` for load balancer probes.

## Security

- **Session auth**: `itsdangerous.URLSafeTimedSerializer` with 24-hour expiry
- **Password hashing**: SHA-256 (per-tenant dashboard passwords)
- **Rate limiting**: ASGI middleware with sliding window counters
- **SQL injection prevention**: All queries use parameterized `$1` placeholders via asyncpg
- **CORS**: Configurable per-tenant `allowed_origins`
- **Input validation**: Pydantic models on all API endpoints
