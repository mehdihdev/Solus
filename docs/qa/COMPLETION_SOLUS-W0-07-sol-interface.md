# Completion Report — SOLUS-W0-07: SOL Reasoning↔Systems Interface Contract

**Branch:** `SOLUSDEV-72-shared-dev-models` (Week-0 contracts). **Status:** complete, integrated,
validation-green, left uncommitted for human review → MR.

---

## What was built

The second critical coordination seam splitting SOL — the COMPLETE list of what the reasoning layer
can ask of the systems layer. Human-owned Week-0 contract (ADR-028); the mock-and-swap seam that lets
Pratham (reasoning) and Mehdi (systems) build in parallel.

- `packages/api/src/solus_api/agent/interfaces.py` — the `SolSystems` Protocol (5 async methods:
  `get_graph_context`, `get_telemetry`, `get_error_history`, `rag_query`, `record_error_solution`) +
  all 11 shapes (`GraphScope`, `ContextBudget`, `EntityRead`, `EdgeRead`, `GraphContext`,
  `TelemetryWindow`, `TelemetryWindowSummary`, `TelemetrySummaryView`, `RetrievalFilter`, `RagHit`,
  `ErrorHit`). Reuses `ArtifactRef` (W0-04) and `SourceRef` (W0-06) — neither redefined.
- `packages/api/src/solus_api/agent/fake_systems.py` — `FakeSolSystems`, a deterministic canned impl
  reasoning builds against now (budget sub-sampling with `truncated`, a telemetry window sequence with
  a `raw_ref`, resolvable `SourceRef` provenance, a recorded id).
- `packages/api/tests/test_sol_interface.py` — mypy structural conformance (`_STRUCTURAL: SolSystems =
FakeSolSystems()`) + functional shape assertions.
- `docs/contracts/sol-interface.md` — the contract doc.

## Governing docs consulted

ADR-028 (human-owned), ADR-027 + `models.py` (`graph_entity`/`graph_edge`/`error_solution`), ADR-026
(routing — a SEPARATE interface), ADR-010/011 (orchestrator + flywheel), CLAUDE.md §7 (tenant
isolation + untrusted ingest). Reuses W0-01, W0-04 (`ArtifactRef`, tools separate), W0-06 (`SourceRef`).

## Design decisions (grounded)

1. **Single `SolSystems` Protocol**, bare (no `@runtime_checkable`) — matches the repo's `Tool`
   precedent; conformance is proven by a mypy-typed assignment + functional tests.
2. **Curated `EntityRead`/`EdgeRead` that OMIT the embedding** (model-consumable), distinct from
   `schemas.py`'s full `GraphEntityRead`. Read models use `from_attributes+frozen`; value objects use
   `frozen+extra="forbid"`.
3. **Reuse, not redefine:** `ArtifactRef` (`agent.tools`) for `raw_ref`; `SourceRef`
   (`fingerprint.contract`) for RAG provenance.
4. **SYS-05 sub-sampling hook** (`degree` + `ContextBudget` → `truncated`) present so the perf work
   fits behind the contract; **telemetry streaming** is a documented same-shape Live Bench extension.

## Test coverage

5 tests; full suite **175 passed**; mypy strict clean (src + tests, 48 files); ruff clean.
Acceptance proven: FakeSolSystems satisfies the Protocol; each method returns well-formed shapes (graph
context with well-formed entities/edges, budget-forced `truncated`, a telemetry window sequence with a
lazy `raw_ref`, error/rag hits honoring `k` with resolvable `SourceRef` provenance, a recorded UUID).

## Phase-4 review outcomes (3 parallel reviewers)

- **Code review — APPROVE** (1 LOW: `max_tokens` is a no-op in the fake, spec-deferred to SYS-05 —
  left as-is, sanctioned).
- **Python review — 1 HIGH (fixed):** the conformance docstring OVERCLAIMED — mypy checks parameter
  types/order/count + return types but NOT parameter _names_ for positional-or-keyword params. Fixed
  by correcting the docstrings (interfaces/fake/test) to state this accurately, and flagging the
  keyword-only hardening (below). Everything else clean (Pydantic modeling, typing, async, determinism).
- **Security review — 2 HIGH + 2 MEDIUM (addressed via documentation, per your decision):**
  - **HIGH — tenant scoping:** `get_error_history` (and `rag_query` over tenant `source_types`) read
    tenant data but `project_id` is optional. **You chose to keep the ticket signature and document.**
    Applied: binding §7 language in the module docstring, `RetrievalFilter`/`get_error_history`/
    `rag_query` docstrings, and doc §5 — systems MUST scope by `filter.project_id`; an absent
    `project_id` is valid ONLY for global corpora (datasheets), never tenant source types; and the
    real impl's conformance suite MUST add a cross-tenant isolation case (documented in the test's
    `_assert_conforms` + doc §5/§8).
  - **MEDIUM — untrusted content:** labeled `chunk`/`solution_text`/`summary`/`anomalies`/`name`/
    `attrs` as attacker-influenceable data the reasoning layer must delimit (module docstring + doc
    §5), incl. the flywheel path (model-generated `solution_text` stays untrusted).
  - **LOW — `EntityRead`/`EdgeRead` omit `extra="forbid"`:** left as-is — both code and Python
    reviewers confirmed this is CORRECT for `from_attributes` read models (extras are ignored, never
    stored); it matches the `schemas.py` read-model convention.

## Flagged for the founders

1. **Tenant scoping is documentation-enforced, not type-enforced (your decision).** `get_error_history`
   / `rag_query` keep the ticket's optional-`project_id` signature; §7 tenant isolation therefore rests
   on the systems impl + the required cross-tenant conformance case + reasoning always passing the
   request's project. Recommended follow-up if you later want it type-enforced: add a mandatory
   `project_id` to `get_error_history` (matching the other three stored-data methods).
2. **Recommended hardening — keyword-only Protocol params.** Making the `SolSystems` params keyword-only
   (`*`) would make mypy enforce parameter _names_ across the independent parallel build (systems'
   real impl), closing the Python-review gap at the source rather than in docs. Not applied (it changes
   the call convention on the ticket-specified signatures); your call.

## Out of scope (documented, not built)

The real systems impls (SYS tickets), the telemetry streaming transport (Live Bench), the reasoning
layer (Pratham), and the RAG/pgvector wiring.

## Human handoff steps

Review the branch + this report; decide the two flags above; `git add`/commit/push, open the MR, merge
after review; the real systems impl must add the cross-tenant isolation conformance case before it ships.
