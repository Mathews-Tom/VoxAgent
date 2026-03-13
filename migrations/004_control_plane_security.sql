ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS admin_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_hash_version TEXT NOT NULL DEFAULT 'argon2id',
    is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (admin_user_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_memberships_admin_user_id
    ON tenant_memberships(admin_user_id);

CREATE INDEX IF NOT EXISTS idx_tenant_memberships_tenant_id
    ON tenant_memberships(tenant_id);

CREATE TABLE IF NOT EXISTS config_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_admin_user_id UUID NOT NULL REFERENCES admin_users(id),
    tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    diff_summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_config_audit_log_tenant_id
    ON config_audit_log(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_config_audit_log_actor_admin_user_id
    ON config_audit_log(actor_admin_user_id, created_at DESC);
