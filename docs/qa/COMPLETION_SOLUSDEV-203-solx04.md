# Completion report — SOLUSDEV-203 (SOLX-04): "SOL connects a missing integration"

**Lane:** C (SOLUSDEV-68) · **Date:** 2026-08-08

## What was built

`agent/connect_integration.py` — three W0-04 tools over the connector registry, registered per-request in `build_sol_registry` (new optional `connectors` param, wired from all three SOL routes via `RegistryDep`):

- **`solus.list_integrations`** (read): the supported roster + per-project connection state, each disconnected provider carrying the inline next step (`solus.connect_integration with provider=…`) — the missing-capability moment offers the connect action in-flow.
- **`solus.connect_integration`** (destructive — `requires_confirmation=True`, Solus-authored `consent_summary`): for committed-export connectors (`AuthKind.NONE`, e.g. KiCad) it creates the live `Source` (validated identity, activity recorded, plan limits honored via `check_can_add_integration` → structured refusal with the upgrade next-step); for OAuth/PAT providers it mutates NOTHING and returns `next_step: complete_oauth_in_app` — a chat turn cannot finish a browser OAuth round-trip, and **credentials never travel through model-visible arguments** (the params schema has no token field, by construction; pinned by test).
- **`solus.verify_integration`** (read): live/connected status for a provider, or the connect next-step. "SOL confirms it is live."

Failure paths are next steps, not dead ends: unknown provider → the supported roster; plan limit → the plan message; connector refusal → the connector's reason + retry guidance.

## The inherited obligation — discharged

`connect_integration` is the app's **first real destructive tool in the SOL registry**, so this ticket carries the route-level e2e the SOLX-01 review deferred here (H3/M7), all passing:

- **do-mode park→approve→execute:** a chat message proposing the connect streams a `tool_confirmation` frame; the `Source` does NOT exist while parked; approving at the decide endpoint executes the stored call and the `Source` is CONNECTED.
- **guide never parks or connects:** same proposal in guide mode → zero `ToolConfirmation` rows, zero `Source` rows, the guide-mode message in the stream.
- **another member cannot decide:** a second same-team member's approve returns `ok=false` and nothing executes (owner-scoped confirmations, no existence leak).

## Verification

`tests/test_connect_integration.py`: 15 tests (8 unit + 7 route/security e2e). Full suite **1760 passed / 3 skipped**; mypy + ruff clean. `docs/api/API-implementation.md` amended (tier-1): the three tools on `GET /sol/tools`. Phase-4 code + security reviews run on the staged backend diff; findings addressed pre-commit (section appended post-review).

## Phase-4 review findings and resolutions

Code review: WARNING (1 HIGH, 3 MEDIUM, 2 LOW). Security review: FAIL (4 HIGH, 4 MEDIUM, 5 LOW). **All HIGHs and all agreed MEDIUMs fixed in-diff**, each pinned by a test; final backend suite 1760/1760 on a quiet tree, and `test_connect_integration.py` runs green three consecutive times (SEC-H4 determinism requirement).

**Fixed:**

- **SEC-H1 / CR-L1 (plan-limit fail-open):** a missing User row now refuses the connect outright (fail closed) instead of silently skipping `check_can_add_integration`.
- **SEC-H2:** `decide_tool_confirmation` now requires a verified email (`RequireVerified`) — the destructive execution point takes the same ADR-009 gate as REST source creation — plus the same frequency-cap admission as the message route (also closes the reviewer's rate-limit LOW). Tested: an unverified token gets 403 and nothing executes.
- **SEC-H3 (both halves):** `request_confirmation` validates args against the descriptor's JSON Schema BEFORE parking — invalid args (e.g. a token-shaped extra key) are refused with `INVALID_ARGS`, never persisted, never rendered, never streamed (`ParkedCall.confirmation_id` is now `None` for refusals and the route never emits a confirmation frame for them); `_argument_rows` passes `redact_text` like the preview path; and the live `tool_call` SSE frame now redacts model-proposed args at the event constructor (persistence already did — the wire now matches). Tested end-to-end with a `ghp_…`-shaped arg: not in the DB, not on the wire.
- **SEC-H4:** the flaky funding helper was replaced with upsert semantics; determinism proven by three consecutive green runs.
- **SEC-M1:** the SOL connect path now emits the consent-aware `source.connected` DataEvent (parity with REST — abuse detection sees chat-originated connects, `via: sol`).
- **SEC-M2 / CR-M2 (duplicate-Source race):** a `pg_advisory_xact_lock` keyed on `(project, provider)` serializes concurrent connects; a `gather`-based test proves exactly one live Source.
- **SEC-M3:** cross-TEAM isolation test added (team B decides team A's confirmation → 404, nothing executes) alongside the existing same-team non-owner test.
- **SEC-M4:** an injection-corpus payload driven at the REAL destructive tool — parks at most, never executes.
- **CR-HIGH (untested failure paths):** the misleadingly-named shape test was replaced by real coverage in the flows (verify-unconnected next-step and roster errors are asserted in the async tests; the plan-limit and ConnectorError branches are exercised via the fail-closed and refusal tests).
- **CR-M3 (PENDING/ERROR dead end):** a non-CONNECTED existing row now returns a concrete `next_step` (finish in-app or disconnect and retry); `_list_integrations` unaffected rows likewise never dead-end.
- **CR-M4 / SEC-L (SourceType drift):** guarded enum coercion — a connector registered ahead of its `SourceType` member degrades to "unsupported" with a log, and `list_integrations` skips it instead of dying mid-loop.
- **SEC-L (config-needing connectors):** a successful connect for a connector with `config_fields` includes the "set … in Integrations" next step rather than claiming full sync readiness.
- **SEC-L (docs table):** the SOLX-04 paragraph sits below the route table (repaired).

**Accepted / noted:** the Redis-absent frequency-cap fail-open remains the flagged pre-GA infra blocker (unchanged posture, now logged loudly by the gateway).

## Deviations / notes

- The tool module lives at `agent/connect_integration.py` (lane-C `agent/` root), NOT `agent/tools/` — that directory is the LANE E carve-out; only the shared `InProcessTool`/shapes are imported from it.
- OAuth connect-from-chat is deliberately a pointer, not an automation: automating a browser credential flow from a model-triggered action would be a §7 violation waiting to happen. Revisit only with a human-designed flow.
