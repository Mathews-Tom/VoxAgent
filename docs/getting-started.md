# Getting Started

This guide walks through setting up VoxAgent for local development and deploying your first voice agent.

## Prerequisites

| Tool    | Version | Install                                                      |
| ------- | ------- | ------------------------------------------------------------ |
| Python  | 3.12+   | [python.org](https://www.python.org/downloads/)              |
| uv      | latest  | `curl -LsSf https://astral.sh/uv/install.sh \| sh`           |
| Node.js | 22+     | [nodejs.org](https://nodejs.org/)                            |
| pnpm    | 9+      | `corepack enable && corepack prepare pnpm@latest --activate` |
| Docker  | 24+     | [docker.com](https://www.docker.com/)                        |

## 1. Clone and Set Up

```bash
git clone https://github.com/Mathews-Tom/VoxAgent.git
cd VoxAgent
```

## 2. Start Infrastructure Services

```bash
docker compose up -d
```

This starts three services:

| Service        | Port  | Purpose                                    |
| -------------- | ----- | ------------------------------------------ |
| PostgreSQL 17  | 5432  | Database for tenants, conversations, leads |
| LiveKit Server | 7880  | Real-time WebRTC audio routing             |
| Ollama         | 11434 | Local LLM inference                        |

Wait for all services to be healthy:

```bash
docker compose ps
```

## 3. Pull an LLM Model

```bash
docker compose exec ollama ollama pull llama3.1
```

This downloads the default LLM model (~4.7 GB). For faster responses on weaker hardware, use a smaller model:

```bash
docker compose exec ollama ollama pull llama3.2:3b
```

Then update the tenant's `llm.model` field accordingly.

## 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set `SESSION_SECRET` to a random string:

```bash
# Generate a random secret
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

The default values in `.env.example` work with the Docker Compose setup. For production, you'll want to change the database credentials and LiveKit keys.

### Required Variables

| Variable             | Description                        |
| -------------------- | ---------------------------------- |
| `DATABASE_URL`       | PostgreSQL connection string       |
| `LIVEKIT_URL`        | LiveKit server WebSocket URL       |
| `LIVEKIT_API_KEY`    | LiveKit API key                    |
| `LIVEKIT_API_SECRET` | LiveKit API secret                 |
| `SESSION_SECRET`     | Secret for signing session cookies |

### Optional Variables

| Variable             | Default                  | Description                        |
| -------------------- | ------------------------ | ---------------------------------- |
| `OLLAMA_BASE_URL`    | `http://localhost:11434` | Ollama endpoint                    |
| `OPENAI_API_KEY`     | —                        | Enables OpenAI as LLM/TTS provider |
| `ELEVENLABS_API_KEY` | —                        | Enables ElevenLabs TTS             |
| `SERVER_HOST`        | `0.0.0.0`                | API server bind address            |
| `SERVER_PORT`        | `8080`                   | API server port                    |
| `LOG_LEVEL`          | `INFO`                   | Logging level                      |

## 5. Install Python Dependencies

```bash
uv sync
```

This creates a virtual environment and installs all dependencies.

For knowledge engine features (RAG, crawling), install the optional group:

```bash
uv sync --group knowledge
```

For Qwen3 TTS (voice cloning):

```bash
uv sync --group tts
```

## 6. Start the API Server

```bash
uv run uvicorn voxagent.server.app:app --reload
```

The server starts at `http://localhost:8080`. Database migrations run automatically on first startup.

Verify it's running:

```bash
curl http://localhost:8080/health
# {"status":"ok"}
```

## 7. Start the Agent Worker

In a separate terminal:

```bash
uv run python -m voxagent.main
```

The agent worker connects to LiveKit and waits for rooms to join.

## 8. Create Your First Tenant

```bash
curl -s -X POST http://localhost:8080/api/tenants \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corp",
    "domain": "acme.com",
    "password": "changeme",
    "llm": {
      "provider": "ollama",
      "model": "llama3.1",
      "system_prompt": "You are the Acme Corp customer support assistant. Be helpful and concise."
    },
    "greeting": "Hi! I'\''m the Acme assistant. How can I help?"
  }' | python3 -m json.tool
```

Save the returned `id` — you'll need it for the widget and dashboard.

## 9. Access the Dashboard

Open `http://localhost:8080/dashboard/login` in your browser.

Log in with:

- **Tenant ID**: The UUID returned when you created the tenant
- **Password**: The password you set (`changeme` in the example)

From the dashboard you can:

- View conversations and transcripts
- Browse extracted leads (with CSV export)
- See analytics (conversation volume, languages, top intents)
- Configure voice settings (STT/LLM/TTS providers)
- Customize the widget (colors, position, greeting)
- Set up webhook URLs for lead routing
- Upload knowledge base documents or crawl websites

## 10. Set Up the Widget

```bash
cd widget
cp .env.example .env.local
pnpm install
pnpm dev
```

Open `http://localhost:3001` to see the demo page with the floating voice button.

### Embed on External Pages

Add this to any HTML page:

```html
<script
  src="http://localhost:3001/widget.js"
  data-tenant-id="YOUR_TENANT_ID"
  data-api-url="http://localhost:8080"
></script>
```

## Ingesting Knowledge

### Via CLI

Crawl a website and build the knowledge index:

```bash
uv run voxagent ingest \
  --tenant YOUR_TENANT_ID \
  --url https://acme.com \
  --depth 3 \
  --max-pages 100
```

Ingest local documents:

```bash
uv run voxagent ingest \
  --tenant YOUR_TENANT_ID \
  --files ./docs/pricing.pdf ./docs/faq.txt ./docs/manual.docx
```

### Via Dashboard

Navigate to **Knowledge Base** in the dashboard and use the upload form or enter a URL to crawl.

After ingestion, the voice agent automatically uses the knowledge base to answer questions with grounded, source-attributed responses.

## Configuring Providers

### LLM Providers

**Ollama (default, local)**:

```json
{
  "llm": {
    "provider": "ollama",
    "model": "llama3.1",
    "temperature": 0.7
  }
}
```

**OpenAI**:
Set `OPENAI_API_KEY` in `.env`, then:

```json
{
  "llm": {
    "provider": "openai",
    "model": "gpt-4.1",
    "temperature": 0.7
  }
}
```

### STT Providers

**Whisper (default)**:

```json
{
  "stt": {
    "provider": "whisper",
    "language": "en",
    "model": "large-v3"
  }
}
```

**Deepgram**:

```json
{
  "stt": {
    "provider": "deepgram",
    "language": "en"
  }
}
```

### TTS Providers

**Qwen3 (default, local)**:

```json
{
  "tts": {
    "provider": "qwen3",
    "voice": "default",
    "language": "en"
  }
}
```

**ElevenLabs**:
Set `ELEVENLABS_API_KEY` in `.env`, then:

```json
{
  "tts": {
    "provider": "elevenlabs",
    "voice": "voice-id-here"
  }
}
```

**Cartesia**:

```json
{
  "tts": {
    "provider": "cartesia",
    "voice": "voice-id-here"
  }
}
```

## Voice Cloning (Qwen3)

Set up a cloned voice from a reference audio sample:

```bash
uv run voxagent voice-setup \
  --tenant YOUR_TENANT_ID \
  --audio ./samples/brand-voice.wav \
  --transcript "This is a sample of our brand voice for cloning purposes."
```

The clone prompt is cached and reused across all utterances for the tenant.

## Setting Up Webhooks

Configure a webhook URL to receive lead data when contacts are extracted from conversations:

1. Go to **Webhooks** in the dashboard
2. Enter your webhook endpoint URL (e.g., a Zapier catch hook)
3. Save

Payload format:

```json
{
  "event": "lead.created",
  "lead": {
    "id": "uuid",
    "tenant_id": "uuid",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+15551234567",
    "intent": "pricing inquiry",
    "summary": "Asked about enterprise pricing plans"
  },
  "dispatched_at": "2024-01-15T10:30:00Z"
}
```

## MCP Tool Integration

Connect external services by adding MCP server configurations to a tenant:

```bash
curl -X PUT http://localhost:8080/api/tenants/YOUR_TENANT_ID \
  -H "Content-Type: application/json" \
  -d '{
    "mcp_servers": [
      {
        "name": "crm",
        "url": "http://localhost:9000/mcp",
        "api_key": "optional-key"
      }
    ]
  }'
```

The agent worker discovers available tools from each MCP server at session start and registers them for LLM use. Tool names are namespaced as `mcp_{server}_{tool}` to prevent collisions.

## Running Tests

```bash
# All tests
uv run pytest

# Unit tests only
uv run pytest tests/unit/

# Integration tests (some need DATABASE_URL)
uv run pytest tests/integration/

# Security tests
uv run pytest tests/security/

# With verbose output
uv run pytest -v
```

## Production Deployment

### Docker

```bash
# Build the backend image
docker build -t voxagent .

# Run the API server
docker run --env-file .env -p 8080:8080 voxagent

# Run the agent worker (same image, different command)
docker run --env-file .env voxagent python -m voxagent.main
```

### Widget

```bash
cd widget
docker build -t voxagent-widget .
docker run -p 3001:3001 \
  -e NEXT_PUBLIC_API_URL=https://api.yourdomain.com \
  -e NEXT_PUBLIC_LIVEKIT_URL=wss://livekit.yourdomain.com \
  voxagent-widget
```

### Checklist

- [ ] Set strong `SESSION_SECRET` and `LIVEKIT_API_SECRET`
- [ ] Use a managed PostgreSQL instance with SSL
- [ ] Deploy LiveKit server with TLS (use `wss://` URLs)
- [ ] Set `allowed_origins` per tenant for CORS
- [ ] Configure `OPENAI_API_KEY` or deploy Ollama with GPU
- [ ] Set `LOG_LEVEL=WARNING` for production
- [ ] Set up monitoring on the `/metrics` endpoint
- [ ] Configure reverse proxy (nginx/Caddy) with TLS in front of the API
