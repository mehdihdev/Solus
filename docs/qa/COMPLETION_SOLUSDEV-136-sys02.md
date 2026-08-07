# Completion report — SYS-02: pgvector infra, gateway embed(), tool executor, RAG retrieval (SOLUSDEV-136)

**Commits:** `209dcc5` (ADR-027 amendment, tier-2 approved in-chat) · `fb68c0e` (HNSW
migration + models.py) · `1c162a5` (gateway embed() + models.yaml + build_embed_fn) ·
`4f74193` (RAG retrieval) · `779086c` (executor + Sentry) · `a63a5e6` (ScaffoldRunner
swap, own commit) · `84fe9a5`+`0a7bb95` (perf probe) · `68f671e` (ratchet extensions) ·
`3477f3d` (Phase-4 security hardening).

## Step-0 audit answers (reported and adjudicated during planning, 2026-08-07)

1. **Embeddings: EXTENDED FP-02, no second path.** The only embedding write path remains
   `fingerprint/ingest.py::_write_embedding` via the `EmbedFn` seam — `git diff` on
   `fingerprint/ingest.py` is EMPTY. Gateway `embed()` implements the accepted proposal
   (`docs/api/gateway-embeddings.md`, which names this ticket); `build_embed_fn` adapts it
   to the same `EmbedFn` shape both ingest and retrieval consume. Human approved bundling
   embed() into this MR and chose the model (openai `text-embedding-3-small`, 1536-d,
   price verified 2026-08-07).
2. **`ToolRegistry.invoke` today:** owns the complete never-raises safety sequence AND the
   only per-call timeout (`asyncio.wait_for`, per-tool override, default 30s). The
   executor EXTENDS it (gate → invoke → observe; batch semaphore + wall-clock budget) —
   it re-times nothing and reimplements nothing.
3. **Gateway tool-calling boundary:** gateway tool-calling does not exist (zero
   tool_call/tool_use references in `orchestration/`). SYS-02's executor runs
   already-selected `ToolCall`s; `ProviderAdapter.stream` / `providers.py` / `gateway.py`
   streaming surface untouched (`git diff` empty). The confirmation SURFACE exists on
   branch `SOLUSDEV-60/ons-ui01-confirmation-surface` — the executor parks at
   `confirmation_refusal` and builds no confirmation handling (no file collision).
4. **Baseline state:** ivfflat lists=100 on both vector columns (built on EMPTY tables —
   degenerate centroids until an unscheduled REINDEX); single alembic head `92499d574b9f`;
   test DB = per-checkout-hash Postgres with pgvector 0.8.2.

## What was built

### 1. pgvector infra — ivfflat → HNSW (ADR-027 amended, human-approved in-chat)

Migration `e3a1c8f27b54` swaps both indexes to `hnsw (m=16, ef_construction=64,
vector_cosine_ops)`; downgrade restores ivfflat. Single head kept. **Decision reasoning:**
ivfflat trains centroids at CREATE INDEX time — ours were built empty, so recall was
degenerate until a manual REINDEX nobody owned, and `lists` needs a ~√rows retune + REINDEX
per corpus order of magnitude. HNSW builds incrementally, is correct built empty, and holds
through ~10⁶ vectors with no parameter changes. **Assumed corpus:** 0 today; 1k–50k
entities/project, ~10⁵ total medium-term; **10× growth (10⁶):** no retune, no REINDEX;
memory cost ~hundreds of MB of graph overhead; only `hnsw.ef_search` (session GUC) would
ever need touching. Future vector-index changes at ≥10⁵ rows must use CREATE INDEX
CONCURRENTLY out-of-band (documented in the migration; entrypoint budget is 120s).

### 2. Gateway embed() (`orchestration/embeddings.py` + models.yaml `embeddings:` entry)

Single chokepoint preserved (ADR-026): model identity/pricing ONLY in models.yaml; sibling
`EmbeddingAdapter` registry reusing `_BaseAdapter._api_key()` (streaming `ProviderAdapter`
NOT widened); MO-03 order (frequency cap → spend gate → call with bounded transient
retry/backoff → idempotent `track_cost` debit by call_id, input tokens only);
`ProviderCredentialsMissingError` when keyless; response validated (count, dimension,
index integrity). **Identity is structurally required** — an identity-less call must opt
in with `allow_unmetered=True` (Phase-4 H1). Per-call input budget `MAX_EMBED_BATCH=256`
/ `MAX_EMBED_CHARS=500k` enforced before the gates (H2). `build_embed_fn` = the one
EmbedFn composition point; never raises (failure → no-signal → consumers degrade).

### 3. RAG retrieval (`solus_api/rag/retrieval.py`) — W0-07 primitive

`rag_query` / `get_error_history` / `record_error_solution` as pure query functions
(param names match the `SolSystems` Protocol for mechanical delegation). **Tenant scoping
is IN the SQL WHERE of all four statements** (ANN + degraded × entity + error) — isolation
holds under any query plan; unscoped tenant queries raise (`ValueError`), never served.
Keyless/failed/malformed embedding degrades to project-scoped Postgres full-text
(`plainto_tsquery`, bound params, `left()`-bounded tsvector input) — same shapes, nothing
raises. `k` clamped to [1, 100]; column selection (embeddings never leave the DB); error
hits carry `SourceRef(source_connector="error_solution", external_ref=str(id))`;
flywheel texts truncated at 100k chars.

### 4. Tool-call execution layer (`agent/tools/exec.py`)

`run_tool` = §7 gate (`confirmation_refusal`, function-local import — cycle-proof,
inherits the SOLUSDEV-60 gate rewrite at call time) → `registry.invoke` → observe. NEVER
raises; no second per-call clock. `run_tool_calls` = semaphore-bounded fan-out (default 4
— caps MCPTool's uncapped per-call subprocess spawn) + optional `asyncio.timeout` batch
budget; expiry → TIMEOUT ToolResults, finished calls keep real results. Logging:
identifiers/counts/sizes only, `%.128r`-escaped (log-forge-proof); Sentry captures are
tags-only own-string messages (never `error.message`). `agent.tool_invoked` events stay
with the SOL loop per the human-owned contract (flagged below). ScaffoldRunner routes
through `run_tool` (2-line swap, own commit `a63a5e6` — lane-sol can drop it in review).

### 5. Sentry (DSN-gated)

`sentry-sdk` dependency + `SOLUS_SENTRY_DSN` (absent → init never runs, all captures are
documented no-ops). Init hardened per security review: `send_default_pii=False`,
`include_local_variables=False` (frame locals carry `call.args`),
`max_request_body_size="never"`, `before_send=_scrub_sentry_event` (strips
`request.query_string` + URL query — OAuth callback codes must never ride an event),
`LoggingIntegration(event_level=None)` (ERROR logs never auto-become events; only
deliberate Solus captures do).

## Verification evidence

- **Full suite: 1537 passed, 3 skipped** (pre-existing live-marker skips), 0 failed.
  `ruff check` + `ruff format --check` clean; `mypy --strict` clean (126 source files);
  `alembic heads` = exactly `e3a1c8f27b54`; live index verified `hnsw` in the test DB.
- **No-fork proofs:** `git diff` EMPTY on `fingerprint/ingest.py`, `providers.py`,
  `gateway.py`; `mock_canonical_parts.json` + W0-05 connector files byte-identical.
- **Retrieval load/latency (perf probe `scripts/perf_rag_retrieval.py`, committed;
  N=10k across 20 projects, C=10, 500 mixed queries):**
  - 282 q/s wall; ANN p50 **38.6ms** / p95 **50.9ms**; degraded (full-text) p50
    **20.4ms** / p95 **36.2ms** (client-side latency includes the test embedder's
    Python-side 1536-dim vector generation; SQL execution itself is ~2.4ms per EXPLAIN).
  - **recall@10 vs forced-exact over 100 sampled queries: 1.000.** EXPLAIN shows the
    planner chose Bitmap Index Scan on `project_id` + top-N heapsort — per-project EXACT
    KNN, as predicted at this per-project cardinality (~500 rows/project): perfect
    recall, tenant scope structurally enforced, vector index not even consulted.
    `hnsw.iterative_scan = relaxed_order` is the documented one-line fallback if the
    planner ever prefers the ANN index with recall loss.
  - **N=100k (the 10× point; isolated DB `solus_test_perf136`, same probe, C=10):**
    163 q/s wall; ANN p50 **75.6ms** / p95 **91.0ms**; degraded p50 **12.9ms** / p95
    **21.3ms**; **recall@10 = 1.000 over 100 samples**. EXPLAIN: planner still chooses
    Bitmap Index Scan on `project_id` + top-N heapsort (per-project exact KNN over ~5000
    rows/project; SQL execution 22.8ms, mostly cold-cache heap reads). Seed time 1125s —
    confirming the migration-doc rule that future index rebuilds at this scale go
    CREATE INDEX CONCURRENTLY out-of-band. The 10× story holds: latency grew with
    per-project cardinality (2.4ms → 22.8ms SQL for 10× rows, roughly linear as the
    exact-KNN plan predicts), recall stayed perfect, no parameter retuning needed. The
    HNSW index becomes load-bearing when per-project cardinality grows enough for the
    planner to prefer it — `hnsw.iterative_scan = relaxed_order` is the documented
    recall guard for that transition.
  - Operational note: the probe must not run concurrently with the pytest suite OR
    across an agent-session turn boundary on the shared per-checkout DB — the suite and
    the H10 stop-gate both truncate it (warned in the script; use
    `SOLUS_TEST_DATABASE_URL` pointed at a dedicated DB, e.g. `solus_test_perf136`).
- **Executor overhead (200 trivial-tool invocations):** bare `registry.invoke` median
  5µs → `run_tool` median 9µs (**+4µs/call**); `run_tool_calls` @ concurrency 4: 200
  calls in 3.0ms. Negligible.
- **Executor behavior:** gated tool refused with `invoke` never awaited; timeout/crash →
  `ok=False` without raising; order preserved; peak-inflight ≤ cap; batch-budget expiry →
  TIMEOUT results; caplog proves args/values never logged; fresh-interpreter ratchet
  proves exec's import graph is `mcp`-free.
- **Retrieval security tests:** cross-tenant isolation ×3 (ANN, error-history, degraded),
  unscoped rejection, NaN/wrong-dim/raise degradation, soft-delete + NULL-embedding
  handling, k clamping, oversized-text truncation, red-team flywheel round-trip
  (adversarial instructions stay inert data in the hit envelope).

## Phase-4 reviews (both subagents ran on the full diff; all actionable findings FIXED)

- **code-reviewer: APPROVE** — 0 CRITICAL/HIGH; 2 doc nits (gateway-embeddings.md status
  → fixed in `68f671e`; ADR-003 cross-ref flagged below).
- **security-reviewer: initial FAIL → all fixed in `3477f3d`** except two flagged items:
  - **C1** (Sentry ships OAuth `?code=` on error events) — FIXED (before_send scrub +
    body-never + LoggingIntegration event_level=None) + tests.
  - **H1/H2** (unmetered-by-default embed; unbounded input) — FIXED + tests.
  - **M1–M4, M6, L1, L3–L5** — FIXED + tests (see commit `3477f3d`).
  - **H3 (retrieval authorization)** — resolved architecturally, NOT by an in-module
    check: §7 mandates authorization through the CENTRALIZED layer and forbids ad-hoc
    per-path auth, so retrieval binds the contract in SECURITY docstrings ("project_id
    MUST come from `deps.get_project_context` / the SOL loop's construction-bound scope,
    never user/model input" — the `build_get_entity_tool` precedent). **Binding handoff
    obligation on SOL-01/02:** the wiring MR must derive `project_id` from `ProjectCtx`
    and add the reviewer's test (member of team B passing team A's project_id → denied at
    the route/context layer).
  - **M5 (pre-existing, NOT ours):** un-allowlisted stdio MCP servers fall back to the
    spec's blanket `requires_confirmation` (`mcp_tool.py:344-351`) — fail-open for
    destructive remote tools on un-vendored servers. MCP-lane code, unchanged by this
    diff. Recommend a follow-up ticket: default `requires_confirmation=True` when no
    `allowlist.yaml` exists.

## Ratchet extensions (deliberate, not gate-faking)

- `test_no_hardcoded_models.py`: SDK-import allowlist gains `orchestration/embeddings.py`
  (the proposal's sanctioned sibling adapter surface).
- `test_fingerprint_labels.py::test_every_v1_modality_is_exercised`: pins the four scored
  modalities explicitly — CTR-08's hardware modalities are declared-but-unscored and
  covered by the matcher fall-through test instead.

## Flags / follow-ups for humans

1. **models.yaml edited** (human-curated file): `embeddings:` entry added with the model
   you chose in-chat. Review at MR.
2. **sentry-sdk is a new dependency with no observability ADR** — ticket named Sentry
   explicitly; an ADR codifying the scrub-everything-by-default posture is owed.
3. **DECISIONS.md ADR-003 "See also" line** still says "ivfflat" post-amendment — one-word
   tier-2 edit awaiting your approval (deliberately not self-approved).
4. **CODEOWNERS:** `solus_api/rag/` belongs to @lane-errors; `agent/tools/exec.py` is
   lane-systems; `runtime.py` swap (commit `a63a5e6`) is lane-sol territory — drop that
   single commit if lane-sol declines.
5. **SOL-01/02 obligations:** H3 authorization test (above); `agent.tool_invoked` event
   emission (contract assigns it to the SOL loop; still implemented nowhere).
6. **Standing gaps (pre-existing, unchanged):** `ToolError.retryable` consumed by nobody;
   loop guard already enforced at runtime.py + routers/sol.py (executor deliberately adds
   no third point); M5 above; `eda.py` hint-key mismatch (CTR-08 report).
7. **COWORK_QA:** not written — SYS-02 and CTR-08 ship no user-facing flows (library +
   infra only); stated here per Phase 5 rather than fabricating a UI test plan.
