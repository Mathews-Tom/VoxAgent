# VoxAgent Runtime Invariants

## Purpose

This document freezes the behavior that the enhancement program relies on. Each later phase may tighten these rules, but it must not violate the invariants without updating this document and the associated tests.

## Auth and Control Plane

| Surface               | Invariant                                                                                  | Notes                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| Dashboard session     | Interactive dashboard access is always backed by a signed session cookie.                  | Browser redirects are acceptable for HTML requests; API requests must return `401`. |
| Tenant admin routes   | Privileged tenant mutation routes must never depend on untrusted tenant identifiers alone. | Role-bearing identity is the future contract.                                       |
| Public onboarding     | Public tenant creation, if retained, must stay narrower than authenticated CRUD.           | Creation flow is distinct from admin management.                                    |
| Secret-bearing config | Stored secret values must not be echoed back in full from read endpoints.                  | Applies to MCP server API keys and outbound webhook credentials.                    |

## Token Issuance

| Surface                 | Invariant                                                                         | Notes                                                    |
| ----------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `/api/token`            | Token issuance requires a syntactically valid tenant ID.                          | Invalid UUIDs are rejected at request validation.        |
| `/api/token`            | Token issuance must only succeed for an existing active tenant.                   | This becomes enforced by runtime checks in later phases. |
| Widget/session identity | Room names and visitor identities must remain derivable without additional state. | Current format is `{tenant_id}_{visitor_id}`.            |
| Public edge trust       | Origin and tenant checks must happen before a LiveKit token is minted.            | Prevents cross-tenant embed abuse.                       |

## Transcript and Conversation Lifecycle

| Surface                   | Invariant                                                                                                                                | Notes                                                                |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Canonical transcript      | Every persisted conversation is derived from a single in-memory transcript/event stream assembled during the session.                    | Later phases normalize this into explicit events.                    |
| Transcript order          | Transcript entries preserve causal order from the voice session.                                                                         | Downstream processors rely on ordering.                              |
| Post-session side effects | Lead extraction, memory updates, webhook dispatch, and handoff dispatch operate on persisted conversation data, not ephemeral callbacks. | Current implementation is synchronous; later phases move it to jobs. |
| Failure visibility        | Downstream failures must be observable in logs and metrics even when the realtime session succeeds.                                      | Silent drops are not acceptable.                                     |

## Knowledge Ingestion

| Surface          | Invariant                                                                                            | Notes                                                       |
| ---------------- | ---------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Source identity  | Ingestion must treat a source URL or uploaded file as a durable logical source.                      | Append-only chunk growth is not a valid long-term contract. |
| Reindex decision | Reindexing is driven by persisted source state, not only files present on disk in memory at runtime. | Current disk hash map is transitional.                      |
| Shared semantics | Dashboard and CLI ingestion must converge on the same source/version model.                          | Operator behavior must be consistent across entry points.   |

## Feature-Flag Contracts

| Flag                                 | Initial Behavior                                              | Future Behavior                                                                  |
| ------------------------------------ | ------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `ENABLE_ASYNC_POST_SESSION_JOBS`     | `false` by default; keeps synchronous post-session execution. | Enables queue-backed execution once Phase 3 lands.                               |
| `ENABLE_MANAGED_KNOWLEDGE_INGESTION` | `false` by default; keeps file-oriented ingestion behavior.   | Enables source/version orchestration once Phase 4 lands.                         |
| `ALLOW_LOCALHOST_WIDGET_ORIGINS`     | `true` by default in development.                             | Allows explicit dev-origin overrides without weakening production origin checks. |
