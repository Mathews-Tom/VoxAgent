# VoxAgent

Open-source, multi-tenant voice AI platform for websites. Embed a `<script>` tag, get a voice assistant grounded in your content — with lead extraction, visitor memory, and a full management dashboard.

Built on [LiveKit](https://livekit.io) for real-time voice, with pluggable STT->LLM->TTS providers and a hybrid RAG knowledge engine.

## Features

- **Voice conversations** — VAD + STT + LLM + TTS pipeline via LiveKit Agents
- **Knowledge grounding** — Hybrid BM25 + FAISS search over crawled websites and uploaded documents
- **Multi-tenant** — Per-tenant STT/LLM/TTS config, knowledge bases, widget theming
- **Lead extraction** — LLM-based contact/intent extraction from transcripts, webhook routing to CRMs
- **Visitor memory** — Cross-session context persistence per visitor
- **Dashboard** — HTMX-based UI for conversations, leads, analytics, and configuration
- **MCP tools** — Connect external services (booking, ticketing) via tenant-configured MCP servers
- **Handoff detection** — Automatic escalation to human agents with webhook triggers
- **Embeddable widget** — Next.js widget with `<script>` tag loader, customizable colors and position

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 22+ and pnpm
- Docker and Docker Compose (for infrastructure services)
- [uv](https://docs.astral.sh/uv/) package manager

### 1. Start infrastructure

```bash
docker compose up -d
```

This starts PostgreSQL, LiveKit server, and Ollama.

### 2. Pull an LLM model

```bash
docker compose exec ollama ollama pull llama3.1
```

### 3. Set up the Python backend

```bash
cp .env.example .env
# Edit .env — set SESSION_SECRET to a random string

uv sync
uv run uvicorn voxagent.server.app:app --reload
```

The API server starts at `http://localhost:8080`. Database migrations run automatically on startup.

### 4. Start the voice agent worker

In a separate terminal:

```bash
uv run python -m voxagent.main
```

### 5. Start the widget (optional)

```bash
cd widget
cp .env.example .env.local
pnpm install
pnpm dev
```

Widget dev server runs at `http://localhost:3001`.

### 6. Create a tenant

```bash
curl -X POST http://localhost:8080/api/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "domain": "acme.com", "password": "secret"}'
```

Access the dashboard at `http://localhost:8080/dashboard/login`.

## Embed on Your Website

Add the widget to any page with:

```html
<script
  src="http://localhost:3001/widget.js"
  data-tenant-id="YOUR_TENANT_ID"
  data-api-url="http://localhost:8080"
></script>
```

## Ingest Knowledge

### Via CLI

```bash
# Crawl a website
uv run voxagent ingest --tenant TENANT_ID --url https://example.com --depth 3

# Ingest local files
uv run voxagent ingest --tenant TENANT_ID --files ./docs/pricing.pdf ./docs/faq.txt
```

### Via Dashboard

Navigate to **Knowledge Base** in the dashboard to upload files or trigger a website crawl.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full system design.

```
Browser Widget ─── WebRTC ──→ LiveKit Server ──→ VoxAgent Worker
                                                    │
                              ┌─────────────────────┤
                              ▼                     ▼
                         STT → LLM → TTS      Knowledge Engine
                              │                (BM25 + FAISS)
                              ▼
                    PostgreSQL (tenants, conversations, leads, memory)
                              │
                    FastAPI Dashboard ← HTMX
```

## Project Structure

```
voxagent/
├── agent/         # Voice agent core, handoff, MCP tools
├── knowledge/     # Crawler, chunker, hybrid search engine
├── plugins/       # STT/LLM/TTS provider factories
├── server/        # FastAPI app, routes, templates, auth, middleware
├── cli/           # CLI commands (ingest, voice-setup)
├── config.py      # Environment-based configuration
├── models.py      # Pydantic data models
├── queries.py     # Database CRUD operations
├── leads.py       # LLM-based lead extraction
├── memory.py      # Visitor memory summarization
├── webhooks.py    # Lead webhook dispatch
├── metrics.py     # Prometheus metrics
└── main.py        # LiveKit agent worker entrypoint

widget/            # Next.js embeddable voice widget
migrations/        # PostgreSQL schema migrations
tests/             # Unit, integration, and security tests
```

## Configuration

All configuration is via environment variables. See [`.env.example`](.env.example) for the full list.

| Variable             | Required | Default                  | Description                                  |
| -------------------- | -------- | ------------------------ | -------------------------------------------- |
| `DATABASE_URL`       | Yes      | —                        | PostgreSQL connection string                 |
| `LIVEKIT_URL`        | Yes      | —                        | LiveKit server WebSocket URL                 |
| `LIVEKIT_API_KEY`    | Yes      | —                        | LiveKit API key                              |
| `LIVEKIT_API_SECRET` | Yes      | —                        | LiveKit API secret                           |
| `SESSION_SECRET`     | Yes      | —                        | Secret for signing dashboard session cookies |
| `OLLAMA_BASE_URL`    | No       | `http://localhost:11434` | Ollama inference endpoint                    |
| `OPENAI_API_KEY`     | No       | —                        | OpenAI API key (enables OpenAI provider)     |
| `ELEVENLABS_API_KEY` | No       | —                        | ElevenLabs TTS API key                       |
| `SERVER_HOST`        | No       | `0.0.0.0`                | API server listen address                    |
| `SERVER_PORT`        | No       | `8080`                   | API server listen port                       |
| `LOG_LEVEL`          | No       | `INFO`                   | Logging verbosity                            |

## Docker Deployment

### Build and run

```bash
# Backend
docker build -t voxagent .
docker run --env-file .env -p 8080:8080 voxagent

# Agent worker
docker run --env-file .env voxagent python -m voxagent.main

# Widget
cd widget && docker build -t voxagent-widget .
docker run -p 3001:3001 voxagent-widget
```

## Testing

```bash
# Run all tests
uv run pytest

# Unit tests only
uv run pytest tests/unit/

# With coverage
uv run pytest --cov=voxagent
```

## API Reference

See [docs/api-reference.md](docs/api-reference.md) for the complete endpoint documentation.

## Documentation

| Document                                   | Description                                      |
| ------------------------------------------ | ------------------------------------------------ |
| [Architecture](docs/architecture.md)       | System design, component interactions, data flow |
| [Getting Started](docs/getting-started.md) | Detailed setup guide with provider configuration |
| [API Reference](docs/api-reference.md)     | All REST and dashboard endpoints                 |

## License

Apache License 2.0 — see [LICENSE](LICENSE).
