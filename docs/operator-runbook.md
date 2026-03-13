# Operator Runbook

## Scope

This runbook covers the operational controls added for queue-backed post-session work, managed knowledge ingestion, and policy-driven rate limiting.

## Health Checks

| Endpoint | Purpose | Expected Result |
|---|---|---|
| `/health/live` | process liveness | `200 {"status":"ok"}` |
| `/health/ready` | API readiness plus DB connectivity | `200 {"status":"ready"}` |
| `/metrics` | Prometheus scrape | includes `voxagent_job_outcomes_total`, `voxagent_rate_limit_decisions_total`, `voxagent_token_issuance_total` |

## Rate Limiting

| Policy | Routes | Default Behavior | Backend Failure Mode |
|---|---|---|---|
| `public` | `/api/token`, widget config | 30 requests / 60s | fail open |
| `auth` | dashboard login/logout | 10 requests / 60s | fail closed |
| `admin` | tenant/dashboard/admin routes | 120 requests / 60s | fail closed |

### Backend Configuration

| Variable | Default | Purpose |
|---|---|---|
| `RATE_LIMIT_BACKEND` | `memory` | `memory` for single-process dev, `redis` for shared counters |
| `RATE_LIMIT_REDIS_URL` | unset | Redis connection string when `RATE_LIMIT_BACKEND=redis` |

### Triage

1. If `voxagent_rate_limit_decisions_total{outcome="backend_error"}` increases on `auth` or `admin`, treat it as a degraded control-plane incident.
2. If Redis is unavailable and public traffic must continue, leave public routes in fail-open mode but restore Redis before scaling workers.
3. If `blocked` grows sharply on `/api/token`, confirm the tenant's embed origin and check for abuse against nonexistent tenant IDs.

## Async Job Backlog

1. Check `voxagent_job_outcomes_total` by `job_type` and `status`.
2. If failures are clustered on `lead_webhook`, inspect the downstream endpoint latency and HTTP status codes.
3. If dead letters accumulate, disable `ENABLE_ASYNC_POST_SESSION_JOBS` only as a last resort and redeploy the API/worker pair together.

## Knowledge Ingestion

1. Use the dashboard to re-crawl or rebuild before touching on-disk artifacts manually.
2. Check `voxagent_knowledge_index_builds_total` for repeated rebuild loops.
3. If a source must be withdrawn quickly, remove it from the dashboard and confirm the next manifest excludes the source key.
