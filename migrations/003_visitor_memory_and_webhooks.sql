-- Cross-session visitor memory
CREATE TABLE visitor_memories (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id),
    visitor_id  TEXT        NOT NULL,
    summary     TEXT        NOT NULL,
    turn_count  INTEGER     NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (tenant_id, visitor_id)
);

CREATE INDEX idx_visitor_memories_lookup ON visitor_memories(tenant_id, visitor_id);

-- Webhook URL for lead routing (per-tenant)
ALTER TABLE tenants ADD COLUMN webhook_url TEXT;

-- MCP server configs (per-tenant, JSONB array)
ALTER TABLE tenants ADD COLUMN mcp_servers JSONB NOT NULL DEFAULT '[]';
