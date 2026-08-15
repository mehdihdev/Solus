# Completion report — SOLUSDEV-200 (SOLX-01): two-mode dispatch (Guide/Do) + destructive-action gate

**Lane:** C (SOLUSDEV-68, branch `SOLUSDEV-68-SOL-Reasoning`) · **Date:** 2026-08-08
**Decision basis:** Phase 0 Decisions 1–3, approved in-chat (ADR-032): port the SOLUSDEV-60 agent-side foundation; one sanctioned `tools/exec.py` reconciliation; keep `a63a5e6`.

## Part A — the ported foundation (from `SOLUSDEV-60/ons-ui01-confirmation-surface`)

- **Structural gate:** `AgentRunContext` carries no registry — descriptors + a gated dispatch closure only (`agent/runtime.py`); `build_dispatch` fuses gate→invoke and wraps it in `exec.run_tool` (the SYS-02 single observable path, reconciled); ratchet `test_only_the_gated_dispatcher_reaches_registry_invoke` pins `registry.invoke(` to exactly {`agent/runtime.py`, `agent/confirmations.py`} — passing.
- **Confirmations round-trip:** `agent/confirmations.py` (park / decide / stale), the decide endpoint on `routers/sol.py` per CTR-03 (approve/reject only; `amend` unconstructible at type+runtime — contracts suite passing), `ToolConfirmation`/`ConfirmationStatus` models, three migrations re-chained onto `e3a1c8f27b54` with their SOLUSDEV-96 revision ids preserved (single head: `a7c41b9d2e05`).
- **Prompt containment:** `agent/prompt.py` — per-turn nonce fencing, untrusted-data JSON containment, caps; injection corpus + red-team suites ported and passing.
- **LlmRunner:** the model-backed runner; refuses unmetered calls (no identity → no model call, ADR-018/019); bounded rounds.
- **Gateway tool-calling:** `stream(conversation=ToolConversation(...))` — ONE parameter on the ONE entry point; frequency cap / spend gate / retry / cost hook shared, not duplicated. Provider tool types + all three adapters.
- **exec.py reconciliation (the sanctioned LANE E touch):** `run_tool(dispatch, call)` is now the observability wrapper around the gated closure — it lost `registry.invoke` and the function-local `confirmation_refusal` import (cycle gone). SYS-02's intent (every dispatch observed) preserved; `run_tool_calls` calls `dispatch` directly to avoid double-logging.

### Port deviations (full detail in the port execution report, reproduced for Mehdi's review)

1. `ConfirmationDecision` defined in `routers/sol.py` (not `schemas.py`, outside the task's ownership) — body verbatim; one-line import swap when 60 merges.
2. Redaction re-export direction inverted: `agent/tools/untrusted.py` re-exports `redact_*` FROM `bridge/frames.py` (60 does the reverse); one implementation either way.
3. `connectors` param dropped from `build_sol_registry` — existed only for excluded `onshape_tools.py`.
4. `test_registry.py` delta not ported — entirely connector/Onshape assertions.
5. **`agent/tools/*` files touched beyond exec.py** (each gate/runner-required, import-traced): `shapes.py` (`consent_summary`, `description_trusted`), `registry.py` (`tools()`), `tool.py` (`ToolPreview`, `preview` kwarg), `untrusted.py` (redaction re-export). → **Mehdi: these four plus exec.py are the LANE E carve-out touches to review.**
6. Excluded entirely: all Onshape/panel/CAD/tool_docs code and tests, panel deps/config, `deps.py` and `core/config.py` deltas (traced: nothing ported needs them).

## Part B — the Guide/Do mode layer (net-new)

- `agent/modes.py`: `ActionMode` (GUIDE/DO — a different axis from ADR-016's SolMode tone setting) and `build_mode_dispatch(mode, descriptors, dispatch)`. **Guide never dispatches a mutation, structurally**: in Guide mode the closure a runner holds refuses `requires_confirmation` tools before the dispatcher is reached. The wrapper composes OUTSIDE the CTR-03 gate — Do mode passes through and the gate still parks/refuses; the mode layer can only narrow, never grant.
- `AgentRunContext.action_mode` (default GUIDE — the safe mode), `MessageCreate.action_mode` (`"guide"`/`"do"`, request-level; per-action refinement is SOL-02's job), assistant-turn attrs carry both `sol_mode` and `action_mode`.
- **Logged per action:** the dispatch wrapper logs `agent.tool_invoked tool=… call_id=… mode=… ok=… mode_refused=…` (identifiers only, §7); `_persist_turn` emits the `agent.tool_invoked` data-collection event per tool turn through the consent-aware `emit_event` — closing the SYS-02 handoff obligation ("assigned to the SOL loop; implemented nowhere").
- `docs/api/API-implementation.md` SOL section amended (tier-1): decide route row + `action_mode` body field.

## Acceptance → evidence

| Acceptance                                        | Evidence                                                                                                                                                                                |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Do action that mutates is blocked until confirmed | `test_confirmations.py` (parks; nothing runs; approve executes server-stored args; reject/expired/stale never execute) + `test_modes.py::test_do_mode_still_hits_the_confirmation_gate` |
| Guide never dispatches a mutation                 | `test_modes.py::test_guide_never_dispatches_a_mutation` (underlying dispatch spy: zero calls) — structural, not an if-in-the-runner                                                     |
| Mode explicit + logged per action                 | `AgentRunContext.action_mode` explicit; `test_modes.py::test_every_action_is_logged_with_its_mode` (also proves argument values never reach the log)                                    |
| Gate unweakened                                   | Ratchet + `test_a_runner_is_handed_nothing_it_could_dispatch_ungated` + amend-refusal contracts suite — all passing unmodified                                                          |

## Verification

- Full `packages/api` suite: **1691 passed, 3 skipped** (was 1540 collected pre-port; +151 net). mypy clean (129 files), ruff clean.
- `alembic heads` = `a7c41b9d2e05`, exactly one (proven by conftest upgrade-to-head on every suite run).
- Phase-4 code review + security review subagents run on the full staged diff; findings addressed before commit.

## Phase-4 review findings and resolutions

Code review: WARNING (1 HIGH, 1 MEDIUM). Security review: FAIL (1 CRITICAL, 4 HIGH, 7 MEDIUM, 7 LOW). All CRITICAL/HIGH and most MEDIUM/LOW **fixed in this diff**; final suite 1702/1702 green. Pinned by `tests/test_solx01_hardening.py` plus targeted additions.

**Fixed:**

- **C1 (consent surface inert):** `_summarize` now fails closed — an untrusted description is never rendered on the approval card (name + sanitized args only); arg keys/values and prose routed through `_single_line`. Producers set the flags: bridge `validate_inventory` descriptors carry `description_trusted=False` + the Solus-authored allowlist `reason` as `consent_summary`; MCP-introspected descriptors are `description_trusted=False`, and a destructive spec default with NO allowlist consent text is **not registered at all** (behavior change; `test_mcp_tool.py` updated accordingly).
- **H1:** with the flags real, `prompt.tool_specs` fencing engages for every fork description (tested with an injection payload).
- **H2:** `redis`/`enqueue` threaded route→context→gateway (wiring test asserts non-None passthrough). ⚠️ Redis/ARQ are NOT yet deployed in this app — until infra lands the gateway frequency cap fails open; **pre-GA blocker**, owned by the orchestration/infra lane.
- **H4:** ratchet widened to any `.invoke(` in agent production code (allowlist: runtime.py, confirmations.py, tools/registry.py) + pattern-evasion test.
- **M5 / code-review HIGH:** `LlmRunner` ends the turn only on a genuine confirmation-gate refusal (UNAUTHORIZED on a `requires_confirmation` descriptor); ordinary failures (hallucinated tool, timeout) flow back for self-correction, and guide-mode refusals get an honest `_GUIDE_TURN` message instead of "I've shown you what it would do".
- **M1:** `park` removed from `AgentRunContext` entirely — reachable only inside the gated dispatch closure; a runner cannot park around the mode layer.
- **M3/M4:** previews bounded by `_PREVIEW_TIMEOUT_SECONDS=10s` (incl. the FOR-UPDATE decide-time re-check) and rows pass `redact_text` before persistence/streaming.
- **M6:** frequency-cap/trial-cap/credit blocks surface as distinct SSE codes, not `internal`.
- **CR-MEDIUM:** post-approval dispatch wrapped in `exec.run_tool` for duration/Sentry parity.
- **L1:** preview migration column got `server_default='[]'` (body deviates from 60's copy by that one argument). **L3:** decide event carries `tool` + `confirmation_id`. **L4:** `sk-live-` fixture prefix → `sk-fake-` (scanner-safe).

**Accepted / deferred, with owners:**

- **H3/M7 (route-level park→stream→decide e2e):** the app registry contains no destructive tool yet, so the full e2e lands with SOLX-04's `connect_integration` (the first real `requires_confirmation` tool). Covered today: service-level round-trip (`test_confirmations`, incl. HTTP decide paths), mode threading e2e (capturing-runner route test). **Explicit obligation on SOLX-04.**
- **M2 (args unvalidated at park):** the card renders stored args (sanitized); execution still validates on approve. Noted for a follow-up; parking invalid args wastes a card but executes nothing.
- **L2 (team_id not predicated on decide):** correct today via ProjectCtx; signature ripple not worth it now — noted.
- **L5 (contract-doc drift):** `contracts/action_gate.py:10` points at `schemas.py` for the decision body; it lives in `routers/sol.py` (tier-2 file — humans edit; flagged here).
- **L6 (mode refusals skip run_tool):** the mode layer's own `agent.tool_invoked` log line covers the outcome; accepted.
- **L7 (orphaned PENDING confirmations on turn abort):** needs a list/cancel surface — that is the CTR-03 approval UI (LANE B) + a small list endpoint; flagged for LANE 0 triage.

## Open items / flags for humans

- **SYS-02 H3 handoff (cross-tenant denial test at the SOL route layer)** remains owed by SOL-01/02 wiring — the decide endpoint's isolation is covered in `test_confirmations.py`; the messages-route ProjectCtx test lands with SOL-01.
- When SOLUSDEV-60 merges: `ConfirmationDecision` import swap, redaction re-export flip, and its panel/tool_docs migrations re-chain (their `down_revision`s referenced excluded revisions). The confirmation migrations themselves will merge clean (same ids, same bodies).
- The `VIRTUAL_ENV` hijack note from the Phase 0 report stands for humans' shells; this worktree now has its own synced venv and `uv run` ignores the mismatched export with a warning.
