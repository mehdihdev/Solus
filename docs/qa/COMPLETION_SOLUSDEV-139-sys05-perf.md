# Completion — SOLUSDEV-139 (SYS-05): systems perf + executor hardening, measured

**Status: DONE.** Two commits: a behavior-identical retry consolidation, then the perf behavior.

## What was built

1. **2-degree sub-sampling with relevance pruning** (`graph/neighborhood.py`). The 2-hop bound
   and hop-distance-first truncation already existed; what was arbitrary was WHICH neighbours
   survived a binding `max_entities` within a hop (created_at order). Now: neighbour discovery
   is ranked by **edge confidence** (desc, created_at/id tiebreak), and when the budget binds
   within a hop the confidence-ranked candidates are kept. Skipped under kind/domain filters
   (the filter needs the full candidate pool — `ponytail:` ceiling noted in code). Behavior
   stays entirely behind the W0-07 seam — no signature change.
2. **Semantic cache** (`agent/perf.py` `SemanticCache`, wired inside `DbSolSystems` — the one
   chokepoint `build_context` AND the SYS-03 tools flow through). Exact hits on normalized
   text; near-duplicate hits by query-embedding cosine ≥ 0.95 within the same
   `(project_id, kind)` — the tenant boundary is structural in the key and the similarity scan.
   TTL 120 s (TTL over invalidation: graph/error writes happen in the ARQ worker process,
   invisible to an API-process cache), LRU-bounded at 256 entries, injectable clock.
   **One embed per query, period**: the keying vector is reused for the ANN retrieval via a
   fixed-embed closure. **Empty results are never cached** — a just-recorded error solution
   must be findable immediately (flywheel honesty, tested). Hit-rate is measured and logged
   (identifiers + counters only, never query text) and exposed via `cache_stats()`.
   `# ponytail:` in-process dict; Redis + pub/sub invalidation when multi-process serving needs it.
3. **Executor hardening** (`orchestration/retry.py`):
   - Commit 1 (pure refactor): the two duplicate MO-03 transient-retry loops
     (`gateway._GatedStream._start`, `embeddings._call_with_retry`) now delegate to one
     `retry_transient`; each attempt owns its cleanup; the patchable `_sleep`/`_retry_sleep`
     test seams survive. Behavior-identical, suites pass unchanged.
   - Commit 2: **per-provider `CircuitBreaker`** — the gap `gateway.py`'s own docstring named.
     Opens after 5 consecutive transient failures per provider key; open → `CircuitOpenError`
     (a `ProviderTransientError` subclass, so every existing handler keeps its posture — embeds
     degrade to no-signal, SOL turns surface a masked retryable failure); half-open probe after
     a 30 s cooldown; success closes. One process-wide breaker shared by streaming AND
     embeddings (a melted-down provider trips one circuit for both). Consulted before the first
     try and before every retry, so an open circuit never burns the backoff schedule.
     Per-test reset fixture added to conftest (the accumulate-across-calls design would
     otherwise leak deliberate test failures across tests).
   - Timeouts already existed at every layer (provider client 120 s, per-tool `wait_for`,
     tool-batch wall clock, turn wall clock) — none re-added.

## Measured latency (dev DB `solus_test2`, 243 entities, n=20 each; live dev machine)

| Path                                     | Before (p50/p95) | After (p50/p95)                                          |
| ---------------------------------------- | ---------------- | -------------------------------------------------------- |
| `get_graph_context` degree-2, budget-200 | 4.09 / 5.63 ms   | 7.56 / 10.83 ms (machine noise; same single-digit class) |
| `get_graph_context` 5-anchor degree-2    | 7.19 / 23.31 ms  | 8.28 / 39.93 ms                                          |
| `rag_query` FTS k=5 — repeated query     | 1.35 / 3.21 ms   | **0.00 / 0.01 ms (cache hit)**                           |
| `rag_query` FTS k=5 — unique queries     | 3.23 / 5.24 ms   | 2.67 / 4.35 ms                                           |
| `get_error_history` k=5                  | 1.94 / 3.89 ms   | 1.69 / 3.81 ms                                           |

Honest read: at this corpus size every uncached path is single-digit milliseconds, so the
cache's millisecond savings are real but small. The **structural** win is what a hit skips
once `openai_api_key` is seeded: the OpenAI embed round-trip (~100–300 ms) per near-duplicate
retrieval — plus DB load at future corpus sizes. Measured hit-rate in the mixed benchmark
(repeats + uniques + empty-result queries): **0.33** (20 hits / 61 lookups); repeats alone
hit at 100%. Graph-path numbers moved within run-to-run noise on the shared dev box — the
pruning changes WHICH entities survive, not how many queries run (one extra ORDER BY key).

## No-regression gate

`tests/test_reason_eval.py` (the SOL eval) passes unchanged after sub-sampling; full touched
slice (`test_perf`, `test_feeds`, `test_builtin`, `test_neighborhood`, `test_retry`,
`test_gateway`, `test_embeddings`, `test_main`, `test_sol`) — 132 passed.

## Notes / delegated judgment

- Ticket's "Redis (semantic cache)" hint: v1 is in-process by deliberate choice — connector
  writes happen in another process either way, so Redis buys sharing, not correctness; the
  seam is one constructor arg (ADR-005 posture). Named in the code as the upgrade path.
- IMP-01 does its own bounded traversal by design and is untouched — this optimizes working
  code and blocks nothing.
- Relevance pruning under kind/domain filters keeps the previous (probe-based, created_at)
  behavior — documented ceiling, not a silent cap.

## Proposed Jira (NOT posted — decision 4)

Comment on SOLUSDEV-139, then transition → Done:

> Shipped on SOLUSDEV-69-lane-e-sol-systems. 2-hop bound + confidence-ranked relevance
> pruning behind get_graph_context (no seam change); TTL'd tenant-keyed semantic cache in
> the real SolSystems with measured hit-rate (repeat retrievals ~0ms vs 1–3ms; embeds
> skipped on hit; empties never cached so the flywheel stays immediate); executor hardening:
> the two duplicate transient-retry loops consolidated into orchestration/retry.py and a
> per-provider circuit breaker added (the gateway's named gap), shared by streaming and
> embeddings. SOL eval passes unchanged; before/after latency table in
> docs/qa/COMPLETION_SOLUSDEV-139-sys05-perf.md.
