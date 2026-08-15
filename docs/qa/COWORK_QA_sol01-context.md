# COWORK QA — SOL-01 (SOLUSDEV-129): context construction

SOL-01 is a backend assembly module with **no user-facing surface of its own yet** — the SOL chat reply that consumes it arrives with SOL-02 (reasoning loop). What a tester can verify today is that nothing regressed and that the module's guarantees hold via its suite; full conversational verification belongs to the SOL-02 QA pass.

Setup: the Solus API checkout with a migrated Postgres+pgvector test database; run commands from `packages/api`.

## Flow 1 — the acceptance suite passes on your machine

1. `env -u VIRTUAL_ENV uv run --no-sync pytest tests/test_context.py -q` → **9 passed**. ☐
2. Read `tests/test_context.py::test_builds_a_cross_domain_context_end_to_end` and confirm the scenario matches the ticket's acceptance: graph + telemetry anomaly + error-with-fix + document, one deterministic rendering with citations. ☐

## Flow 2 — regression on the SOL chat surface

1. `POST /api/v1/projects/{id}/sol/conversations` then a message → SSE streams and completes as before (SOLX-01 QA Flow 1). ☐
2. Cross-tenant: a no-team user POSTing into your conversation → **404** (also pinned by `test_cross_tenant_message_post_is_denied`). ☐

## Deferred to SOL-02 QA

- A chat reply whose content visibly draws on graph/telemetry/error context with citations — that is the reasoning loop consuming `build_context`; re-test conversationally there.
