# Completion report — SOLUSDEV-129 (SOL-01): context construction

**Lane:** C (SOLUSDEV-68) · **Date:** 2026-08-08 · **Re-scope honored:** the Aug-1 mode/gate additions landed first in SOLX-01 (`88eaed8`); this ticket is the context-assembly core on top.

## What was built

`packages/api/src/solus_api/agent/context.py` — `build_context(systems, query, *, project_id, scope, window, budget, k)` over the **W0-07 `SolSystems` Protocol only** (never systems internals), returning a frozen, inspectable `Context` of `ContextSection`s with `render()` / `tokens()`.

- **All four feeds:** `get_graph_context` (entities + named cross-domain edges), `get_telemetry` (window progression incl. anomalies), `get_error_history` (with recorded fixes), `rag_query` — tenant `project_id` threaded into the graph pull and every `RetrievalFilter`, derived from `ProjectCtx` by callers, never from content (the SYS-02 H3 posture; the reviewer's cross-tenant POST-messages denial test landed here too).
- **Ranked, deduped, packed:** hits interleave across feeds by score (deterministic citation tie-break); duplicate chunks collapse with the error-feed copy winning (it carries the fix); under `ContextBudget.max_tokens` the least relevant hits drop first, telemetry trims oldest-window-first, and the systems-bounded graph pull is the floor. Dropped hits are recorded **by citation** on the object — "why did SOL reason this way" is answerable from `Context` itself.
- **Attribution:** every hit renders with a `[connector:ref]` citation from its W0-06 `SourceRef`.
- **Token estimate:** local `len//4` heuristic, same shape as the gateway's `type_estimator` knob — deliberately not coupled to routing config; calibrate both together.
- **Fencing is downstream by design:** `render()` output is DATA; `agent/prompt.py` (shipped in SOLX-01) nonce-fences it at prompt assembly. SOL-02 wires the two together.

## SYS-04/ERR-02 seam (recorded per the charter)

`FakeSolSystems` is still the only W0-07 implementation (SYS-04 and ERR-02 are unstarted systems-lane tickets). SOL-01 builds against the Protocol — the seam working as designed; the same suite re-runs against real impls when SYS-04 lands (`SolSystems` is a structural Protocol, no adapter glue here).

## Acceptance → evidence (`tests/test_context.py`, 9 tests)

| Acceptance                        | Test                                                                                                                                                 |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cross-domain bug case end to end  | `test_builds_a_cross_domain_context_end_to_end` (electrical entities + soldered_to edge + telemetry anomaly + I2C error + datasheet doc, one render) |
| Relevance ranking, not naive dump | `test_hits_are_ranked_by_relevance_across_feeds` (0.92 err > 0.88 doc > 0.81 err > 0.74 doc, interleaved)                                            |
| Budget packing                    | `test_budget_drops_the_least_relevant_hit_first`, `test_budget_floor_keeps_the_scoped_graph`                                                         |
| Source attribution                | `test_every_retrieved_hit_carries_source_attribution`                                                                                                |
| Deterministic, inspectable        | `test_context_is_deterministic` (against a provenance-pinned double), `dropped` tuple asserted                                                       |
| Dedupe                            | `test_duplicate_chunks_across_feeds_appear_once`                                                                                                     |
| H3 handoff                        | `test_cross_tenant_message_post_is_denied` (route-level 404, no existence leak)                                                                      |

## Verification

Suite green (context tests 30/30 incl. 12 parametrized red-team cases; full-suite run at commit), mypy + ruff clean.

## Phase-4 review findings and resolutions

Security review: FAIL (3 CRITICAL, 3 HIGH). Code review: WARNING (1 HIGH). **All fixed in this diff**, each pinned by a test:

- **C1 (citation forgery):** provenance strings could mint labels/extra citations ("[datasheet:trusted]") — citation components now charset-restricted (`[A-Za-z0-9._/#:@-]`) and capped at 128, mirroring `SAFE_REMOTE_NAME`.
- **C2 (ingested content set the token bill):** a megabyte `attrs` blob blew a 100-token budget 1000× and evicted every legitimate hit — every untrusted field is now capped pre-render (`_CHUNK_CAP`/`_FIELD_CAP`), the graph floor is clipped under the budget, and `Context.tokens() <= max_tokens` holds unconditionally with the clip recorded in `dropped`.
- **C3 (redaction gate skipped):** entity `attrs`, chunks, fixes, and summaries now pass `redact_value`/`redact_text` — the same gate as every other path into model context.
- **SEC-H1 (tenant scoping untested):** a recording fake now fails if the tenant filter is removed — graph, telemetry, and both retrieval calls must receive the request's `project_id`.
- **SEC-H2 (no red-team coverage):** the injection corpus is parametrized through entity name, attrs, chunk, and recorded fix; structure and citations must survive every payload.
- **SEC-H3 (fencing claim was documentary):** `Context.fenced(nonce)` is now the model-facing surface (one nonce-fenced data block per section, citation inside the fence); a ratchet test forbids `.render()` in production code.
- **CR-HIGH (best-fit packing):** packing is now a strict relevance cutoff — the first hit that does not fit ends packing; a smaller low-score hit can no longer displace a better one. Telemetry trims are recorded in `dropped` (CR-MEDIUM).
- Also: `k` clamped to `MAX_K=20` (SEC-M1).

**Dispositions:** SEC-M2 (cross-tenant conformance test against the REAL systems impl) is SYS-04's contract-test obligation — recorded there. SEC-M3 (structured event per context build) belongs to the consuming loop which holds the session (same reasoning as `agent.tool_invoked`) — lands with SOL-02. SEC-L2 (two token heuristics) accepted with the calibration note.

## Deviations / notes

- `window=None` skips the telemetry pull entirely (no fabricated windows). Callers pass a window when the query context warrants it — SOL-02's classification decides.
- `DEFAULT_K = 5` and all RAG knobs are deliberately unturned: SOL-02 owns tuning against the eval set.
