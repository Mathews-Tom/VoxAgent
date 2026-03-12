# API Reference

Base URL: `http://localhost:8080`

## Health & Metrics

### `GET /health`

Returns server status.

**Response** `200`:
```json
{"status": "ok"}
```

### `GET /metrics`

Prometheus-formatted metrics (conversations, leads, latency, etc.).

**Response** `200`: `text/plain` with Prometheus exposition format.

---

## Token (Widget Connection)

### `POST /api/token`

Generates a LiveKit access token for a visitor to join a voice room.

**Request body**:
```json
{
  "tenant_id": "uuid"
}
```

**Response** `200`:
```json
{
  "token": "eyJ...",
  "room_name": "{tenant_id}_{visitor_id}",
  "livekit_url": "ws://localhost:7880",
  "visitor_id": "uuid"
}
```

**Errors**: `422` if `tenant_id` is missing.

---

## Tenants

All tenant endpoints are unauthenticated (intended for admin/provisioning use).

### `POST /api/tenants`

Create a new tenant.

**Request body**:
```json
{
  "name": "Acme Corp",
  "domain": "acme.com",
  "password": "optional-dashboard-password",
  "stt": {
    "provider": "whisper",
    "language": "en",
    "model": "large-v3"
  },
  "llm": {
    "provider": "ollama",
    "model": "llama3.1",
    "temperature": 0.7,
    "system_prompt": "You are a helpful assistant."
  },
  "tts": {
    "provider": "qwen3",
    "voice": "default",
    "language": "en"
  },
  "greeting": "Hello! How can I help?",
  "widget_color": "#6366f1",
  "widget_position": "bottom-right",
  "allowed_origins": ["https://acme.com"],
  "webhook_url": "https://hooks.zapier.com/...",
  "mcp_servers": [
    {"name": "crm", "url": "http://crm:9000/mcp", "api_key": "key"}
  ]
}
```

All fields except `name` and `domain` are optional with sensible defaults.

**Response** `201`: Tenant object (excludes `password_hash`).

### `GET /api/tenants`

List all tenants.

**Response** `200`: Array of tenant objects.

### `GET /api/tenants/{tenant_id}`

Get a single tenant.

**Response** `200`: Tenant object. `404` if not found.

### `PUT /api/tenants/{tenant_id}`

Update a tenant. All fields are optional — only provided fields are updated.

**Request body**: Same schema as create, but all fields optional.

**Response** `200`: Updated tenant object. `404` if not found.

### `DELETE /api/tenants/{tenant_id}`

Delete a tenant.

**Response** `204` on success. `404` if not found.

### `GET /api/tenants/{tenant_id}/config`

Public endpoint for the widget to fetch display configuration.

**Response** `200`:
```json
{
  "greeting": "Hello! How can I help?",
  "widget_color": "#6366f1",
  "widget_position": "bottom-right"
}
```

---

## Leads

### `GET /api/tenants/{tenant_id}/leads`

List extracted leads for a tenant.

**Query parameters**:
| Param | Type | Default | Range |
|-------|------|---------|-------|
| `limit` | int | 50 | 1–500 |
| `offset` | int | 0 | 0+ |

**Response** `200`:
```json
[
  {
    "id": "uuid",
    "tenant_id": "uuid",
    "conversation_id": "uuid",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+15551234567",
    "intent": "pricing inquiry",
    "summary": "Asked about enterprise pricing.",
    "extracted_at": "2024-01-15T10:30:00Z"
  }
]
```

### `GET /api/tenants/{tenant_id}/leads/export`

Export leads as CSV.

**Response** `200`: `text/csv` streaming response with headers: `id, name, email, phone, intent, summary, extracted_at`.

---

## Dashboard (HTML)

All dashboard routes require session authentication. Unauthenticated requests redirect to the login page.

### Authentication

#### `GET /dashboard/login`

Renders the login form.

#### `POST /dashboard/login`

Form-based login.

**Form fields**:
- `tenant_id` — UUID of the tenant
- `password` — Dashboard password

Sets a `voxagent_session` cookie (signed, 24-hour TTL) on success. Redirects to conversations page.

#### `POST /dashboard/logout`

Clears the session cookie. Redirects to login.

### Conversations

#### `GET /dashboard/{tenant_id}/conversations`

Paginated list of conversations with visitor ID, duration, language, and timestamp.

**Query parameters**: `limit` (default 50), `offset` (default 0).

#### `GET /dashboard/{tenant_id}/conversations/{conversation_id}`

Detailed view of a single conversation with the full turn-by-turn transcript.

### Leads

#### `GET /dashboard/{tenant_id}/leads`

Table view of extracted leads with name, email, phone, intent, and timestamp.

**Query parameters**: `limit` (default 50), `offset` (default 0).

### Analytics

#### `GET /dashboard/{tenant_id}/analytics`

Analytics dashboard with:
- Total conversations and leads
- Average conversation duration
- Conversations by language
- Conversations over time (last 30 days)
- Top 10 intents

### Knowledge Base

#### `GET /dashboard/{tenant_id}/knowledge`

Knowledge base management page.

#### `POST /dashboard/{tenant_id}/knowledge/upload`

Upload a file (PDF, DOCX, TXT) to the knowledge base.

**Form field**: `file` — the document to ingest.

#### `POST /dashboard/{tenant_id}/knowledge/crawl`

Crawl a website and add it to the knowledge base.

**Form fields**:
- `url` — Website URL to crawl
- `depth` — Crawl depth (default 3)
- `max_pages` — Maximum pages to crawl (default 100)

### Voice Config

#### `GET /dashboard/{tenant_id}/voice-config`

Voice settings page showing current STT/LLM/TTS configuration.

### Widget Config

#### `GET /dashboard/{tenant_id}/widget-config`

Widget appearance configuration form.

#### `POST /dashboard/{tenant_id}/widget-config`

Save widget settings.

**Form fields**: `widget_color`, `greeting`, `widget_position`, `allowed_origins` (multiple).

### Webhooks

#### `GET /dashboard/{tenant_id}/webhooks`

Webhook configuration page.

#### `POST /dashboard/{tenant_id}/webhooks`

Save webhook URL.

**Form field**: `webhook_url` — URL to POST lead data to.

---

## Webhook Payload

When a lead is extracted and the tenant has a `webhook_url` configured, VoxAgent sends a POST request:

```json
{
  "event": "lead.created",
  "lead": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "tenant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+15551234567",
    "intent": "pricing inquiry",
    "summary": "Asked about enterprise pricing and support tiers.",
    "extracted_at": "2024-01-15T10:30:00+00:00"
  },
  "dispatched_at": "2024-01-15T10:30:05+00:00"
}
```

The webhook fires asynchronously after lead extraction. Failures are logged but do not affect the conversation flow.

---

## Handoff Webhook

When handoff is triggered, VoxAgent sends a POST to the configured handoff webhook:

```json
{
  "tenant_id": "uuid",
  "conversation_id": "uuid",
  "reason": "explicit_request | repeated_failure | keyword_match",
  "transcript": [
    {"role": "user", "content": "I want to speak to a human"},
    {"role": "assistant", "content": "Let me connect you..."}
  ],
  "triggered_at": "2024-01-15T10:30:00+00:00"
}
```

---

## Error Responses

All error responses follow this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request (invalid input) |
| `401` | Not authenticated |
| `403` | Forbidden (wrong tenant) |
| `404` | Resource not found |
| `422` | Validation error (missing/invalid fields) |
| `429` | Rate limited |
| `500` | Internal server error |

### Rate Limits

| Scope | Limit |
|-------|-------|
| Per IP | 30 requests / 60 seconds |
| Per tenant | 100 requests / 60 seconds |

Exceeding the limit returns `429 Too Many Requests`.
