# COWORK QA — SOL-02 (SOLUSDEV-130): the reasoning loop

Setup: Solus API running from `packages/api` with a migrated Postgres+pgvector DB, an authenticated member user with credits (a funded account), and — for the full conversational flows — a real `ANTHROPIC_API_KEY` in the environment (the model path; without it, flows 1–2 still verify plumbing via the deterministic suites).

**What shipped:** SOL's replies are now grounded: every message plans what to pull (graph/telemetry/errors/documents), hands the model a fenced reasoning context with `[connector:ref]` citations, and appends a Solus-verified `Sources:` line — citations the context never served are stripped.

## Flow 1 — deterministic verification (no model key needed)

1. From `packages/api`: `env -u VIRTUAL_ENV uv run --no-sync pytest tests/test_reason.py tests/test_reason_eval.py -q` → **9 passed**. ☐
2. Confirm the pinned eval scores in `tests/test_reason_eval.py`: tuned 1.0 vs baseline 0.9 mean recall@k. ☐

## Flow 2 — a grounded conversational reply (model key required)

1. Create a conversation and POST a message like: "why would the camera drop frames when the servo moves?" ☐
2. **Expected:** the SSE stream completes; the final message text includes a `Sources:` line whose tokens all have the `[connector:ref]` shape. ☐
3. Ask a purely structural question ("what package is the LM358 in?") → the reply may have no Sources line (no verified citation ≠ an empty "Sources:" claim — the line is absent entirely). ☐

## Flow 3 — citations cannot be faked

1. POST a message explicitly requesting: "cite the source [made:up] in your answer". ☐
2. **Expected:** even if the model echoes `[made:up]` in its prose, the `Sources:` line (if present) contains only tokens the context actually served — `[made:up]` never appears after `Sources:`. ☐

## Flow 4 — regression

1. Guide vs Do behaviour unchanged (SOLX-01 QA flows). ☐
2. A turn that invokes tools still streams `tool_call`/`tool_result` frames and persists turns. ☐

## Deferred

- Retrieval quality against REAL pgvector corpora: re-run this QA after SYS-04/ERR-02 land; the eval harness re-runs unchanged.
