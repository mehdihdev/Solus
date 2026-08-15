# COWORK QA — SOLX-01 (SOLUSDEV-200): Guide/Do dispatch + destructive-action gate

Self-sufficient test plan for Claude Cowork. Setup: the Solus API running locally (`packages/api`, `uv run uvicorn solus_api.main:app` with a Postgres+pgvector database migrated to head), an authenticated user with `member` role on a team+project, and an HTTP client that can consume Server-Sent Events. No model API key is needed — the app boots with the deterministic ScaffoldRunner in tests; with a real key the LlmRunner streams real replies (either works for these flows; the gate behaves identically).

**What shipped:** SOL's tool dispatch is now structurally gated. Every message names an action mode — `guide` (default: SOL explains, never mutates) or `do` (SOL may operate tools; destructive ones require your explicit approval). Destructive tool calls park as confirmations you approve or reject; approve executes exactly what the server stored, never what a client resends.

Base path: `/api/v1/projects/{project_id}/sol`.

## Flow 1 — a conversation streams with the default (guide) mode

1. `POST /conversations` `{"title": "QA"}` → **201**, note `id`. ☐
2. `POST /conversations/{id}/messages` `{"content": "What is entity <any-uuid>?"}` → **200**, `text/event-stream`; events arrive and the stream ends with a `done` marker. ☐
3. `GET /conversations/{id}/turns` → the assistant turn's `attrs` contain `"action_mode": "guide"` and `"sol_mode"`. ☐

## Flow 2 — the message body validates `action_mode`

1. Send `{"content": "hi", "action_mode": "do"}` → **200**, streams. ☐
2. Send `{"content": "hi", "action_mode": "demolish"}` → **422** validation error. ☐
3. Send `{"content": "hi", "action_mode": "do", "extra": 1}` → **422** (unknown fields rejected — StrictModel). ☐

## Flow 3 — the confirmation decide endpoint honors CTR-03

(Requires a parked confirmation. In a fixtures-capable environment, park one by driving a `requires_confirmation` tool through a `do`-mode turn; otherwise exercise the endpoint's refusal paths with a random UUID.)

1. `POST /confirmations/{unknown-uuid}` `{"decision": "approve"}` → **200** with `data.ok = false` (not-found is not an error status — HTTP 200 does not mean the action ran). ☐
2. `{"decision": "amend"}` → **422**. There is deliberately no amend — reject, then re-propose. ☐
3. `{"decision": "approve", "args": {"width": 999}}` → **422** (client-supplied args at decision time are rejected wholesale). ☐
4. With a real parked confirmation: approve → the tool executes with the ORIGINAL proposed args; a second approve of the same id → `data.ok = false` (no replay). ☐
5. A user from a DIFFERENT team, valid auth: decide against your confirmation id → **404** (tenant isolation; the id's existence is not revealed). ☐

## Flow 4 — tenant + ownership isolation on conversations (regression)

1. Teammate B (same project, different user): `GET /conversations/{your-id}` → **404** (creator-owned). ☐
2. User from another team: any `/sol/*` call with your project_id → **404**. ☐

## Edge cases

- Empty content `{"content": "   "}` → **422** "must not be blank". ☐
- Content over 8000 chars → **422**. ☐
- Stream interrupted client-side mid-turn → server persists the turn without crashing (re-fetch turns; no 500s in logs). ☐

## Data-collection events (consent-aware)

- With `data_collection_consent = true`: after a turn that invoked tools, the events store contains one `agent.tool_invoked` row per tool call with payload `{tool, call_id, action_mode, ok}` — and **no argument values**. ☐
- With consent false: no rows are written (the structured log line still appears server-side). ☐

## Cross-feature interactions

- `GET /sol/tools` still lists descriptors; bridge-backed tools appear when the local bridge is up (unchanged behaviour). ☐
- Billing/budget: with a real model key and a team at its spend cap, a `do`-mode turn is refused by the gateway pre-flight, not silently unmetered. ☐
