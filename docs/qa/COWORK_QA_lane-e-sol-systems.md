# Cowork QA — LANE E: SOL Systems (SOLUSDEV-69)

What shipped: SOL now answers from the project's REAL data (graph, live telemetry, recorded
errors) instead of canned fixtures; four new read tools (`query_graph`, `get_telemetry`,
`retrieve_errors`, `run_checkers`) are available to SOL; retrieval is semantically cached;
provider keys seed via `make seed-secrets`. This file is self-sufficient — you need the running
app and nothing else.

## Required setup

1. Services: `make db-up` → `cd packages/api && uv run alembic upgrade head` → `make mcp-forks`
   → `make seed-secrets` → `pnpm dev:all`. Root `.env` must hold `SOLUS_SECRETS_KEY`,
   `ANTHROPIC_API_KEY` (required), and ideally `OPENAI_API_KEY` (else retrieval runs on
   full-text, which is expected degradation — not a failure).
2. Account: a signed-in user who is a member of a project team. For grounded answers, the
   project should have a connected Onshape source that has synced (Sources page shows
   "connected", entity count > 0). An EMPTY project is also a required test subject below.
3. `make seed-secrets` printout to expect: `anthropic_api_key stored`, `brave_api_key stored`,
   `google_api_key stored from $GEMINI_API_KEY`, `openai_api_key` stored or skipped — names and
   lengths only. �0 If any secret VALUE ever prints: FAIL, stop, report.

## Flow 1 — SOL answers from YOUR project (the headline)

1. Open the project with synced entities → SOL chat → ask: "What are the main components in
   this project? Name specific parts."
2. ☐ The stream shows tool activity (tool calls/results) and a final answer.
3. ☐ The answer names entities that actually exist in this project (cross-check against the
   Graph screen / Sources entity list).
4. ☐ **The answer contains NO invented parts** — specifically none of: "LM358", "camera_node",
   "/image_raw", "100nF", a motor-current telemetry spike, an "I2C address 0x68 conflict".
   These were the old fixture fictions; any one of them appearing = FAIL.
5. ☐ Refresh the conversation list: the turn persisted (user, tool, assistant turns visible).

## Flow 2 — Empty is honest

1. Create a brand-new project (no sources). Ask SOL the same question.
2. ☐ SOL says the project has no data / nothing synced yet. It must NOT invent components.
3. ☐ No error frames; the turn completes normally.

## Flow 3 — The new tools are offered and work

1. In the project with data, ask: "Run the compatibility checkers on <a real part name>" and
   "What does the graph around <that part> look like?"
2. ☐ SOL can invoke `run_checkers` / `query_graph` (tool events stream) and reports structured
   results (warnings list — possibly empty on a healthy graph — is a PASS; invented warnings
   are a FAIL).
3. ☐ Ask "Any recent telemetry?" with nothing streaming → SOL reports none (empty windows), not
   fabricated signals. If Live Bench is streaming samples, the summary must reflect them.
4. ☐ Ask "Have we seen errors like X before?" on a fresh project → "no recorded history",
   never invented past incidents.

## Flow 4 — Cross-tenant isolation (permission boundary)

1. Two accounts, two teams (A and B), each with a project; A's project has synced data.
2. From B's account, ask SOL about A's parts by name, and (if you can capture one) by entity
   UUID: "Look up entity <A's uuid>".
3. ☐ SOL/B sees nothing of A's: lookups return not-found/empty; answers never quote A's part
   names, errors, or telemetry. Any leak = CRITICAL FAIL.
4. ☐ B cannot open A's conversations (404, not 403 — no existence hint).

## Flow 5 — Degradation paths

1. Remove/blank `OPENAI_API_KEY` (or skip seeding it): SOL retrieval still works (full-text);
   API logs show a compact "embed_one degraded to no-signal … make seed-secrets" warning, not
   a traceback storm. ☐
2. Unseed `anthropic_api_key` on a THROWAWAY database: the first SOL message fails with a
   clear provider-credentials error surfaced as a masked, structured chat error — never a
   stack trace in the UI. ☐
3. Repeat an identical question twice in a row: the second answer's retrieval is served from
   cache (faster; identical grounding). No stale cross-contamination: a question asked in
   project A never surfaces project B's cached results (covered by Flow 4 too). ☐

## Flow 6 — Seeding idempotency

1. Run `make seed-secrets` twice. ☐ Identical output both times, exit 0, names+lengths only.
2. Unset every key env var and run: ☐ all rows "skipped", exit 1, helpful message naming the
   variables.

## Cross-feature interactions

- ☐ Live Bench: stream telemetry into the project (Flow: bench → ingest), then ask SOL "what's
  happening with <signal>?" — the summary must reflect the real buffered samples.
- ☐ Onshape actions still work through chat (list documents etc.) — the new tools must not
  have displaced the `onshape.*` set (check GET /tools or just exercise one).
- ☐ Destructive actions (e.g. `onshape.set_variable` via chat) still park for confirmation —
  the new read tools must never prompt for confirmation.

## Edge cases

- ☐ Ask about a malformed UUID ("look up entity not-a-uuid") → polite tool error, no crash.
- ☐ A very long question (2–3k chars) → normal handling (or a clean validation error).
- ☐ Unverified-email account: chatting works; approving a destructive confirmation is refused
  until verified.
