CREATE TABLE tenants (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT        NOT NULL,
    domain           TEXT        UNIQUE NOT NULL,
    stt_config       JSONB       NOT NULL DEFAULT '{}',
    llm_config       JSONB       NOT NULL DEFAULT '{}',
    tts_config       JSONB       NOT NULL DEFAULT '{}',
    greeting         TEXT        NOT NULL DEFAULT 'Hello! How can I help you today?',
    widget_color     TEXT        NOT NULL DEFAULT '#6366f1',
    widget_position  TEXT        NOT NULL DEFAULT 'bottom-right',
    allowed_origins  JSONB       NOT NULL DEFAULT '[]',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversations (
    id               UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID             NOT NULL REFERENCES tenants(id),
    visitor_id       TEXT             NOT NULL,
    room_name        TEXT             NOT NULL,
    transcript       JSONB            NOT NULL DEFAULT '[]',
    language         TEXT             NOT NULL DEFAULT 'en',
    duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    started_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
    ended_at         TIMESTAMPTZ
);

CREATE TABLE leads (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    conversation_id UUID        NOT NULL REFERENCES conversations(id),
    name            TEXT,
    email           TEXT,
    phone           TEXT,
    intent          TEXT,
    summary         TEXT,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_conversations_tenant_id ON conversations(tenant_id);
CREATE INDEX idx_conversations_started_at ON conversations(started_at);
CREATE INDEX idx_leads_tenant_id ON leads(tenant_id);
