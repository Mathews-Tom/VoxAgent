# Deployment Checklist

## Scope

This checklist is the rollout guardrail for the event spine, async jobs, and managed knowledge ingestion changes.

## Order of Operations

1. Apply database migrations before deploying worker or API code.
2. Deploy API and realtime worker code compatible with both old and new schema.
3. Deploy the async job worker after the API paths can enqueue jobs.
4. Enable feature flags only after the worker is healthy and metrics are visible.

## Pre-Deploy Checks

| Check | Expected State |
|---|---|
| `migrations/007_conversation_events.sql` applied | `conversation_events` table present |
| `migrations/008_job_resilience.sql` applied | unique `leads(conversation_id)` index present |
| `/health/live` | returns `200` |
| `/health/ready` | returns `200` and confirms DB reachability |
| job worker | polling without repeated failures |
| metrics | `voxagent_job_outcomes_total` and `voxagent_post_session_stage_duration_seconds` visible |

## Rollout Flags

| Flag | Default | Enable When |
|---|---|---|
| `ENABLE_ASYNC_POST_SESSION_JOBS` | `false` | worker is deployed and healthy |
| `ENABLE_MANAGED_KNOWLEDGE_INGESTION` | `false` | operators are ready to use managed source lifecycle |

## Post-Deploy Checks

1. Create a test conversation and verify both `conversations` and `conversation_events` rows exist.
2. Confirm a lead-producing conversation yields at most one lead row for the conversation.
3. Confirm failed jobs transition to retry/dead-letter states instead of blocking the realtime worker.
4. Re-crawl a knowledge source and verify the latest version appears in the dashboard.
5. Remove a knowledge source and verify the manifest rebuild excludes it.

## Rollback Notes

1. Disable `ENABLE_ASYNC_POST_SESSION_JOBS` before rolling back worker code.
2. Keep schema additions in place; the new tables and indexes are backward-compatible.
3. If a rollback is needed, redeploy the previous API/worker image pair together rather than mixing versions.
