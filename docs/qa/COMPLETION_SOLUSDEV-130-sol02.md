# Completion report — SOLUSDEV-130 (SOL-02): the reasoning loop

**Lane:** C (SOLUSDEV-68) · **Date:** 2026-08-08 · **Re-scope honored:** Guide/Do resolution + gate routing shipped in SOLX-01; this ticket adds the loop's judgment on top.

## What was built

- **`agent/reason.py`** — the deterministic halves of reasoning:
  - `plan_query(query) -> QueryPlan`: WHAT to pull — graph anchors (UUIDs in the query), traversal degree (2, the SYS-05 lever's ceiling), a telemetry window only for runtime-shaped queries (word-set heuristic, tuned against the eval), retrieval `k`, and the context token budget. No model call (the ADR-026 pattern: classification that gates spend never spends). **WHICH model answers stays with the gateway's `resolve_routing`** — the single routing brain is not duplicated.
  - `verified_citations` / `with_sources`: the model is instructed (`prompt._CITE_NOTE`) to cite `[connector:ref]` tokens and end diagnoses with a concrete fix; only citations the assembled Context **actually served** survive into the Solus-authored Sources line. A hallucinated citation never gains provenance (§7: model output is untrusted).
- **`LlmRunner` wiring** (`runtime.py`): per run — plan → `build_context` (SOL-01) → `Context.fenced(nonce)` handed to the model as per-section data blocks in the opening turn, alongside the fenced user message; both final-reply paths post-process through `with_sources`.
- **The eval** (`tests/fixtures/sol_eval_cases.py` + `tests/test_reason_eval.py`): a labeled cross-domain corpus (2 errors-with-fixes, 4 documents across datasheet/ROS) served by `EvalSystems` (deterministic word-overlap ranking honoring `k`), 5 cases with expected citations, scored as mean recall@k.

## Recorded scores (pinned in-repo by the eval test)

| Config                                                                  | Mean recall@k |
| ----------------------------------------------------------------------- | ------------- |
| Naive baseline (k=1, degree=0, no telemetry)                            | **0.9**       |
| Tuned plan (`plan_query`: k=5, degree=2, telemetry-when-runtime-shaped) | **1.0**       |

Plus: every case individually reaches full recall under the tuned plan, and the runtime-shaped case pulls telemetry only when planned. **Scope stated plainly:** until SYS-04/ERR-02 land, these scores measure the reasoning layer's planning + packing against a controlled corpus — not real pgvector retrieval quality. The harness re-runs unchanged against the real impl (same W0-07 Protocol).

## Acceptance → evidence

| Acceptance                                             | Evidence                                                                                                                                                                                             |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Loop selects tools/models via the gateway              | `LlmRunner` streams through `gateway.stream(conversation=…)`; routing via `resolve_routing` (unchanged, deliberate)                                                                                  |
| Context engineering improves quality vs naive baseline | eval: 1.0 vs 0.9 mean recall@k, pinned                                                                                                                                                               |
| RAG tuning (k/filters) measured against the eval       | knobs live in `reason.py` with the eval named as their change-gate                                                                                                                                   |
| Explanation + suggested fix with citations             | `_CITE_NOTE` (cite verbatim, end with a concrete fix) + `with_sources` verification; integration test proves the fenced context reaches the provider and a fabricated citation never reaches Sources |
| Eval suite with scored outputs                         | `test_reason_eval.py`, exact scores asserted                                                                                                                                                         |

## Verification

Full suite **1741 passed / 3 skipped**; mypy clean (131 files); ruff clean. Red-team harness updated (`systems=FakeSolSystems()`) so the injection suite now exercises the context path too — all red-team tests still pass unmodified in their assertions. Phase-4 code + security reviews run on the staged diff; findings addressed pre-commit (section appended after review).

## Phase-4 review findings and resolutions

Code review: WARNING (1 HIGH, 2 MEDIUM). Security review: FAIL (4 HIGH, 2 MEDIUM). **All HIGHs fixed in-diff**, pinned by tests:

- **SEC-H1 (model-forgeable Sources line):** provenance is now STRUCTURED — `AgentEvent.message(content, citations=…)` carries Solus-verified citations as event data the model cannot reach; `reason.sanitize_reply` strips any model-authored `Sources:` line from the prose. UI obligation recorded for the chat surface (SOLX-02): render citations in their own region, never linkified, display-capped.
- **SEC-H2 (hostile refs in the trusted surface):** `@` dropped from the citation charset; refs stay charset-restricted + capped; the structured channel plus the SOLX-02 render rules close the phishing-shaped-display path.
- **SEC-H3 (retrieval burst ahead of the cap):** `plan_query` caps anchors at 8 and sets `max_entities=200` (the SYS-05 lever, actually pulled); `post_message` now frequency-gates TURN ADMISSION with a proper 429 before any feed runs (the gateway still gates each model round; both consume capacity, double-recording is deliberate and documented). Redis-absent fail-open remains the flagged pre-GA infra blocker.
- **SEC-H4 (runner-seam coverage):** a recording+poisoned systems test pins `project_id == ctx.project_id` on every feed call and proves a poisoned chunk cannot mint provenance; the 429 route test proves zero feed work past the cap.
- **CR-HIGH / SEC-M1 (telemetry citations unverifiable):** telemetry citations now route through the citation sanitizer (`+` was outside the charset); a test round-trips a telemetry citation through `verified_citations`.
- **SEC-M2 (misattribution limit):** documented on `sanitize_reply` — the citation list proves "these sources were in context", not per-claim faithfulness; renderers must not oversell it. Per-claim binding is future work.
- LOWs: shared `UUID_RE` (one parser instance), eval fixture passthrough deleted, `_RUNTIME_WORDS` over/under-trigger noted as an eval-gated tuning knob (CR-M1), eval-corpus-smaller-than-k methodology noted (CR-M2 — widen with distractors when real corpora exist; the scope note already bounds the claim).

## Deviations / notes

- Context is built once per run, not per tool round — a mid-turn tool result does not re-pull the context (rounds share one fenced context; re-planning per round is a future tuning knob, noted for the eval to justify).
- `SEC-M3` from SOL-01 (structured event per context build) remains with the loop; the `agent.tool_invoked` + turn events cover the interaction record today — flagged, not silently dropped.
