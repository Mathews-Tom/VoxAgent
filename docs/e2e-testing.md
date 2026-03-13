# End-to-End Testing Guide

Manual end-to-end testing procedure for the full VoxAgent system. Covers infrastructure setup, tenant management, authentication, knowledge ingestion, voice conversations, leads, webhooks, analytics, rate limiting, and metrics.

## Prerequisites

- Docker and docker-compose
- `uv` (Python package manager)
- A browser (Chrome/Firefox)
- `curl` and `jq`
- `lk` CLI (`brew install livekit-cli`)
- A microphone (for voice testing)

## Phase 1 — Infrastructure

### 1.1 Start backing services

```bash
docker compose up -d postgres livekit ollama
```

Wait for healthy:

```bash
docker compose ps
# postgres should show "healthy"
```

> **Apple Silicon note:** If the ollama container fails with `could not select device driver "nvidia"`, remove the `deploy.resources.reservations` block from `docker-compose.yml`. Ollama runs on CPU without issue on M1/M2/M3.

### 1.2 Pull an Ollama model

```bash
curl -s http://localhost:11434/api/pull -d '{"name":"llama3.1"}' | tail -1
```

Confirm:

```bash
curl -s http://localhost:11434/api/tags | jq '.models[].name'
# Should include "llama3.1:latest"
```

### 1.3 Verify database connectivity

```bash
psql postgresql://voxagent:voxagent@localhost:5432/voxagent -c "SELECT 1"
```

### 1.4 Configure environment

```bash
cp .env.example .env
# Defaults work for local docker-compose.
# Set SESSION_SECRET to any random string.
```

### 1.5 Start the API server

```bash
uv run uvicorn voxagent.server.app:app --host 127.0.0.1 --port 8080 --reload
```

Verify:

```bash
curl -s http://localhost:8080/health/live
# {"status":"ok"}

curl -s http://localhost:8080/health/ready
# {"status":"ready"}
```

### 1.6 Start the LiveKit voice worker (separate terminal)

```bash
uv run python -m voxagent.main start
```

---

## Phase 2 — Tenant CRUD

### 2.1 Create a tenant (no password)

```bash
curl -s -X POST http://localhost:8080/api/tenants \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Acme Corp",
    "domain": "acme.example.com",
    "greeting": "Welcome to Acme!",
    "widget_color": "#3b82f6",
    "widget_position": "bottom-right"
  }' | jq .
```

**Verify:** 201 response, body has `id`, `name`, default `stt`/`llm`/`tts` configs.

```bash
TENANT_ID=<paste UUID here>
```

### 2.2 Create a tenant with password and custom LLM

```bash
curl -s -X POST http://localhost:8080/api/tenants \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Beta Inc",
    "domain": "beta.example.com",
    "password": "s3cret",
    "llm": {
      "provider": "ollama",
      "model": "llama3.1",
      "temperature": 0.5,
      "system_prompt": "You are a customer support agent for Beta Inc."
    }
  }' | jq .
```

**Verify:** 201, custom `llm` config reflected, `password_hash` NOT in response.

```bash
BETA_ID=<paste UUID here>
```

### 2.3 List tenants

```bash
curl -s http://localhost:8080/api/tenants | jq '.[].name'
# "Beta Inc", "Acme Corp" (descending by created_at)
```

### 2.4 Get single tenant

```bash
curl -s http://localhost:8080/api/tenants/$TENANT_ID | jq .name
# "Acme Corp"
```

### 2.5 Get nonexistent tenant

```bash
curl -s -o /dev/null -w '%{http_code}' \
  http://localhost:8080/api/tenants/00000000-0000-0000-0000-000000000000
# 404
```

### 2.6 Update tenant (partial)

```bash
curl -s -X PUT http://localhost:8080/api/tenants/$TENANT_ID \
  -H 'Content-Type: application/json' \
  -d '{"greeting": "Hey there! How can Acme help?"}' | jq .greeting
# "Hey there! How can Acme help?"
```

**Verify:** other fields (name, widget_color) preserved unchanged.

### 2.7 Get widget config

```bash
curl -s http://localhost:8080/api/tenants/$TENANT_ID/config | jq .
# {"greeting":"Hey there! How can Acme help?","widget_color":"#3b82f6","widget_position":"bottom-right"}
```

### 2.8 Delete tenant

```bash
curl -s -o /dev/null -w '%{http_code}' -X DELETE \
  http://localhost:8080/api/tenants/$TENANT_ID
# 204
```

Confirm gone:

```bash
curl -s -o /dev/null -w '%{http_code}' \
  http://localhost:8080/api/tenants/$TENANT_ID
# 404
```

### 2.9 Re-create for subsequent phases

```bash
curl -s -X POST http://localhost:8080/api/tenants \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Acme Corp",
    "domain": "acme.example.com",
    "password": "acme123",
    "greeting": "Welcome to Acme!",
    "llm": {
      "provider": "ollama",
      "model": "llama3.1",
      "system_prompt": "You are a helpful assistant for Acme Corp. Ask for the users name and email."
    }
  }' | jq .id
TENANT_ID=<paste new UUID>
```

---

## Phase 3 — Authentication & Dashboard

### 3.1 Login page renders

Open `http://localhost:8080/dashboard/login` in a browser.

**Verify:** login form with tenant ID and password fields.

### 3.2 Login with valid credentials

Enter the tenant UUID and password `acme123`. Submit.

**Verify:** redirected to `/dashboard/{tenant_id}/conversations`. Session cookie `voxagent_session` visible in DevTools > Application > Cookies.

### 3.3 Login with wrong password

Log out, try again with password `wrong`.

**Verify:** stays on login page, 401, error message displayed.

### 3.4 Login with nonexistent tenant

Enter `00000000-0000-0000-0000-000000000000` as tenant ID.

**Verify:** 401, error message.

### 3.5 Login with invalid UUID format

Enter `not-a-uuid` as tenant ID.

**Verify:** 400, error message.

### 3.6 Logout

Click logout (or POST `/dashboard/logout`).

**Verify:** redirected to login page. Visiting `/dashboard/{tenant_id}/conversations` redirects back to login.

### 3.7 API auth check (no cookie)

```bash
curl -s -o /dev/null -w '%{http_code}' \
  http://localhost:8080/dashboard/$TENANT_ID/conversations
# 302 (redirect to login)
```

---

## Phase 4 — Knowledge Base (RAG)

### 4.1 CLI ingestion — website crawl

```bash
uv run python -m voxagent.cli.main ingest \
  --tenant $TENANT_ID \
  --url https://docs.livekit.io/agents/ \
  --depth 1 \
  --max-pages 5
```

**Verify:** pages crawled, chunks created. Directory `data/$TENANT_ID/knowledge/` contains `chunks.json`, `bm25_corpus.json`, `faiss.index`, `hash_map.json`.

### 4.2 CLI ingestion — file upload

```bash
echo "Acme Corp pricing: Basic plan \$10/month, Pro plan \$50/month, Enterprise custom." > /tmp/pricing.txt
uv run python -m voxagent.cli.main ingest \
  --tenant $TENANT_ID \
  --files /tmp/pricing.txt
```

**Verify:** index updated, chunks include pricing content.

### 4.3 Dashboard knowledge upload

Log into the dashboard. Navigate to Knowledge Base (`/dashboard/{tenant_id}/knowledge`).

Upload a `.txt` or `.pdf` file via the file picker and click "Upload & Index".

**Verify:** success message, source listed under "Indexed Sources".

### 4.4 Dashboard website crawl

On the same page, enter a URL in the crawl form and submit.

**Verify:** crawl runs, results appear.

### 4.5 Re-ingestion (idempotent)

Run the CLI ingest command again with the same URL.

**Verify:** unchanged pages skipped.

---

## Phase 5 — Voice Conversation (LiveKit)

### 5.1 Generate a token

```bash
curl -s -X POST http://localhost:8080/api/token \
  -H 'Content-Type: application/json' \
  -d "{\"tenant_id\": \"$TENANT_ID\"}" | jq .
```

**Verify:** response includes `token` (JWT), `room_name` (format `{tenant_id}_{visitor_id}`), `livekit_url`, `visitor_id`.

Save the room name:

```bash
ROOM_NAME=<paste room_name>
```

### 5.2 Join the room

```bash
lk room join --url ws://localhost:7880 --api-key devkey --api-secret devsecret \
  --identity visitor "$ROOM_NAME"
```

**Verify in worker logs:**

- Room joined, tenant config loaded, agent session started.
- Speaking into microphone triggers STT transcription.
- LLM generates a response.
- TTS speaks the response back.

### 5.3 Test knowledge-grounded response

Ask the agent: "What are your pricing plans?"

**Verify:** response references the pricing info from the knowledge base (Basic $10, Pro $50, Enterprise custom).

### 5.4 Test system prompt adherence

The agent should ask for your name and email (per the system prompt).

Provide: "I'm Alice, alice@acme.com"

### 5.5 End the conversation

Disconnect from the room (Ctrl+C).

**Verify in worker logs:**

- Conversation saved to database.
- Lead extraction runs.
- Lead created (if contact info was provided).

---

## Phase 6 — Conversations Dashboard

### 6.1 View conversations list

Log into dashboard. Navigate to Conversations (`/dashboard/{tenant_id}/conversations`).

**Verify:** the conversation from Phase 5 appears with room name, visitor ID, duration, timestamp.

### 6.2 View conversation detail

Click on a conversation.

**Verify:** transcript displayed with role labels (User / Assistant), content matches what was spoken.

### 6.3 Pagination

Conduct multiple voice sessions. Verify navigation controls paginate correctly.

---

## Phase 7 — Leads

### 7.1 API — list leads

```bash
curl -s "http://localhost:8080/api/tenants/$TENANT_ID/leads" | jq .
```

**Verify:** the lead from Phase 5 appears with name, email, intent, summary.

### 7.2 API — pagination

```bash
curl -s "http://localhost:8080/api/tenants/$TENANT_ID/leads?limit=1&offset=0" | jq 'length'
# 1
```

### 7.3 API — CSV export

```bash
curl -s "http://localhost:8080/api/tenants/$TENANT_ID/leads/export" -o leads.csv
head leads.csv
```

**Verify:** CSV headers: `id,tenant_id,conversation_id,name,email,phone,intent,summary,extracted_at`. Data row contains Alice's info. Response headers include `Content-Type: text/csv` and `Content-Disposition: attachment`.

### 7.4 Dashboard — leads page

Navigate to Leads in the dashboard.

**Verify:** leads displayed in a table.

---

## Phase 8 — Webhooks

### 8.1 Set up a webhook receiver

In a separate terminal:

```bash
python3 -c "
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        print(json.dumps(body, indent=2))
        self.send_response(200)
        self.end_headers()

HTTPServer(('', 9999), H).serve_forever()
"
```

### 8.2 Configure webhook URL

```bash
curl -s -X PUT http://localhost:8080/api/tenants/$TENANT_ID \
  -H 'Content-Type: application/json' \
  -d '{"webhook_url": "http://localhost:9999/webhook"}' | jq .webhook_url
# "http://localhost:9999/webhook"
```

Or via dashboard: navigate to Webhooks page, enter URL, save.

### 8.3 Trigger a webhook

Conduct a voice conversation where you provide contact info. End the session.

**Verify:** the webhook receiver prints:

```json
{
  "event": "lead.created",
  "lead": {
    "id": "...",
    "tenant_id": "...",
    "conversation_id": "...",
    "name": "...",
    "email": "...",
    ...
  },
  "dispatched_at": "..."
}
```

### 8.4 Clear webhook

Clear the URL on the Webhooks dashboard page and save.

**Verify:** `webhook_url` is `null` on the tenant API.

---

## Phase 9 — Widget & Voice Config Dashboard

### 9.1 Widget config page

Navigate to Widget Config in the dashboard.

**Verify:** form shows current greeting, color, position, allowed origins.

### 9.2 Update widget config

Change greeting to "Hi! Need help?", color to `#ef4444`, add origin `https://example.com`. Save.

```bash
curl -s http://localhost:8080/api/tenants/$TENANT_ID/config | jq .
# Updated greeting and color
```

### 9.3 Voice config page

Navigate to Voice Config.

**Verify:** displays current STT/LLM/TTS provider settings.

---

## Phase 10 — Analytics Dashboard

Navigate to Analytics (`/dashboard/{tenant_id}/analytics`).

**Verify:**

- Total conversations count matches database.
- Total leads count matches.
- Average duration is plausible.
- Language breakdown shown.
- 30-day chart renders.
- Top intents listed.

---

## Phase 11 — MCP Tool Integration

### 11.1 Configure an MCP server

```bash
curl -s -X PUT http://localhost:8080/api/tenants/$TENANT_ID \
  -H 'Content-Type: application/json' \
  -d '{
    "mcp_servers": [
      {"name": "weather", "url": "http://localhost:3001/mcp", "api_key": null}
    ]
  }' | jq .mcp_servers
```

### 11.2 Run a voice session

If an MCP server is running at that URL, conduct a conversation that triggers the tool.

**Verify in worker logs:** MCP tool discovered, tool call made, result incorporated.

> Skip this phase if no MCP server is available. Unit tests cover the integration code.

---

## Phase 12 — Visitor Memory (Cross-Session)

### 12.1 First conversation

Join a voice session. Say your name ("I'm Bob").

### 12.2 Second conversation (same visitor)

Generate a new token. Join with the same visitor identity. Ask "Do you remember me?"

**Verify:** the agent references previous context.

Inspect directly:

```bash
psql postgresql://voxagent:voxagent@localhost:5432/voxagent \
  -c "SELECT visitor_id, summary, turn_count FROM visitor_memories WHERE tenant_id = '$TENANT_ID';"
```

> Note: `visitor_id` is generated per token call, so cross-session memory testing requires reusing the same `visitor_id`.

---

## Phase 13 — Rate Limiting

### 13.1 IP rate limit (120/min)

```bash
for i in $(seq 1 121); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health/live)
  [ "$CODE" = "429" ] && echo "Rate limited at request $i" && break
done
# Rate limited at request 121
```

**Verify:** requests 1-120 return 200, request 121 returns 429 with body `{"detail":"Rate limit exceeded"}`.

### 13.2 Tenant rate limit (300/min)

```bash
for i in $(seq 1 301); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' \
    "http://localhost:8080/api/tenants/$TENANT_ID/leads")
  [ "$CODE" = "429" ] && echo "Rate limited at request $i" && break
done
```

> The IP limit (120) will trigger before the tenant limit (300) when testing from a single IP. To test tenant limiting specifically, use different source IPs or lower the IP limit temporarily.

---

## Phase 14 — Metrics

```bash
curl -s http://localhost:8080/metrics
```

**Verify:** Prometheus-format response with `voxagent_` prefixed metrics (conversations count, leads count).

---

## Phase 15 — Error Conditions

### 15.1 Missing required fields

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8080/api/tenants \
  -H 'Content-Type: application/json' -d '{"domain":"x.com"}'
# 422 (name is required)
```

### 15.2 Invalid UUID in path

```bash
curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/api/tenants/not-a-uuid
# 422
```

### 15.3 Token for nonexistent tenant

```bash
curl -s -X POST http://localhost:8080/api/token \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id": "00000000-0000-0000-0000-000000000000"}'
```

**Verify:** token is generated (LiveKit creates rooms on demand), but the voice worker fails to load tenant config — check worker logs for the error.

### 15.4 Lead extraction with no transcript

Verify in worker logs: empty transcript skips lead extraction, no lead created.

---

## Phase 16 — Cleanup

```bash
# Stop the server and worker (Ctrl+C in each terminal)
docker compose down -v
rm -rf data/
```

---

## Test Matrix

| Phase | Component           | Steps | External Dependencies             |
| ----- | ------------------- | ----- | --------------------------------- |
| 1     | Infrastructure      | 6     | Docker, Postgres, LiveKit, Ollama |
| 2     | Tenant CRUD         | 9     | Postgres                          |
| 3     | Auth & Dashboard    | 7     | Postgres, browser                 |
| 4     | Knowledge/RAG       | 5     | Ollama (embeddings), filesystem   |
| 5     | Voice Conversation  | 5     | LiveKit, Ollama, microphone       |
| 6     | Conversations UI    | 3     | Postgres, browser                 |
| 7     | Leads               | 4     | Postgres                          |
| 8     | Webhooks            | 4     | HTTP receiver                     |
| 9     | Widget/Voice Config | 3     | Browser                           |
| 10    | Analytics           | 1     | Postgres, browser                 |
| 11    | MCP Tools           | 2     | MCP server (optional)             |
| 12    | Visitor Memory      | 2     | LiveKit, Postgres                 |
| 13    | Rate Limiting       | 2     | None                              |
| 14    | Metrics             | 1     | None                              |
| 15    | Error Conditions    | 4     | None                              |
| 16    | Cleanup             | 1     | Docker                            |
