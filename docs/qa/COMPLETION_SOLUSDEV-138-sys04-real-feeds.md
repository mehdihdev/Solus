# Completion — SOLUSDEV-138 (SYS-04): real `SolSystems` feeds behind W0-07

**Status: DONE, live-verified.** SOL no longer answers from fiction.

## What was built

- **`agent/feeds.py` — `DbSolSystems`**, the real W0-07 implementation. Pure assembly, zero new
  query paths: `get_graph_context` → `load_neighborhood` + `to_graph_context` (the ONE traversal,
  shared with the focus engine); `get_telemetry` → `TelemetryPlumbing` (signature already
  Protocol-identical); `get_error_history`/`rag_query`/`record_error_solution` → SYS-02
  `rag/retrieval.py`. Holds a sessionmaker (opens a short-lived session per call — the SSE
  generator streams after the request session closes), the live telemetry plumbing, and an
  optional best-effort embed fn. Zero-I/O `__init__` (app constructible without a DB).
- **`degree` clamped to `MAX_DEPTH=2`** (Protocol allows any `ge=0`; the traversal raises above 2)
  with `truncated=True` reported on clamp — conservative honesty, never a masked 500.
  `budget.max_entities` maps to the traversal's SQL-limit sub-sampling; `max_tokens` is left to
  the context packer (its owner).
- **`GraphScope.domains` honored in-query**: additive `domains` param on `load_neighborhood`
  (same semantics as `entity_types` — narrows reached AND traversed-through, roots always kept;
  unknown names sanitized to match nothing, filtered in SQL, never post-hoc). No existing caller
  changed.
- **Production swap**: `main.py` now wires `app.state.sol_systems = DbSolSystems(sessionmaker,
telemetry_plumbing, embed=build_embed_fn(secret_store, allow_unmetered=True))`, placed after
  the telemetry plumbing it wraps.
- **`FakeSolSystems` demoted** to `tests/fixtures/fake_systems.py`; all 6 importing test files
  updated; every `src/` mention (code, comments, docstrings) scrubbed; **ratchet**
  `test_feeds.py::test_fake_sol_systems_is_banished_from_production` asserts zero references
  under `src/solus_api` forever.
- **Conformance split (locked decision 3)**: `_assert_conforms` was pinning FAKE behaviors, not
  the contract. The contract half now lives in `tests/fixtures/sol_contract.py::assert_core_contract`
  (shapes, provenance, intra-context edge integrity, k honored, flywheel id) and runs against
  BOTH impls; fake-specific expectations (non-empty windows, present `raw_ref`, unfiltered
  tolerance) moved into the fake's own test where they are honestly labeled.
- **Docs made current**: RUNBOOK §2 warning replaced with the verified reality; CAPABILITIES
  headline reclassified WORKS with the fix + live evidence; API-implementation phrasing updated.

## Test coverage (all green; suite slices 145+ passing)

`tests/test_feeds.py`: core contract against the real DB; **cross-tenant isolation across every
feed in one test** (graph roots from another project resolve to nothing; telemetry buffer scoped
by key; retrieval scoped in-query); **unfiltered tenant retrieval refusal asserted as a passing
guarantee**; degree clamp; in-query domains narrowing (incl. unknown-domain-matches-nothing);
budget truncation with no dangling edges; **empty-project honesty** (every feed returns empty,
never invented); `record_error_solution` commit proven via a second session; embed forwarding to
all three retrieval paths; the banishment ratchet. Existing suites (`test_sol.py`,
`test_context.py`, `test_connect_integration.py`, `test_sol_runtime.py`, `test_reason.py`,
`test_sol_red_team.py`, `test_neighborhood.py`, `test_main.py`, `test_reason_eval.py`) pass
unchanged against the swapped wiring.

## The acceptance gate — live turn, 2026-08-15

Against the dev API (hot-reloaded), project `solus_test2` (243 Onshape `part` entities), question
"What are the main components in this project? Name specific parts.":

- **4 real tool calls streamed and succeeded**: `onshape.list_documents`,
  `onshape.list_elements` ×2, `onshape.get_assembly_definition` — all `ok: true`.
- **The answer described the actual Kinova Gen3 project**: `Base_assembly`,
  `GEN3_SIMPLIFIED_SHOULDER-86587__ASM`, `Kinova_link1–4`, `BICEP_CONTROL_ASM`,
  `Kinova_gripper`, the Robotiq `2F85` gripper, `XHand_iPhone_Mounting`.
- **Zero fiction**: no LM358, no `camera_node`, no `/image_raw`, no 100nF, no `soldered_to`,
  no invented motor-current telemetry — checked across the entire SSE capture.
- All 6 turns persisted (user, 4 tool, assistant); zero `error` frames.
- Note: the graph FEED contributes anchored context when the prompt carries entity UUIDs
  (`plan_query` extracts anchors); this prompt had none, so grounding flowed through real
  retrieval + real tools. Feed correctness itself is pinned by the test suite above.

## Decisions under delegated judgment / flags

- **Embeds at the seam are unmetered** (locked decision 2): `allow_unmetered=True` — flagged
  against **ADR-019** as agreed. Bounded by the metered, frequency-capped turn admission;
  degrades loudly (compact warning naming the fix) to full-text retrieval while
  `openai_api_key` is unseeded.
- **Clamped degree reports `truncated=True`** even when nothing deeper existed — conservative;
  documented in the adapter.
- `GraphScope.domains == []` is treated as "no filter" (mirrors the `entity_types` truthiness
  convention); non-empty lists filter, unknown values match nothing.

## Proposed amendment to `docs/contracts/sol-interface.md` (human signs; NOT applied)

§8 currently ends: _"`test_sol_interface.py` calls every method and asserts well-formed shapes;
systems runs the same checks against its real impl."_ The code has now proven the precise
semantics; proposed replacement for that sentence:

> The CORE contract assertions live in `tests/fixtures/sol_contract.py::assert_core_contract`
> and run against BOTH the fake and the real impl (`test_feeds.py`). Three fake behaviors are
> deliberately NOT contract: telemetry may be honestly empty (`windows=[]`), `raw_ref` is
> Optional and a real impl may never set it (Live Bench work), and unfiltered tenant retrieval
> is REFUSED by a real impl (`ValueError` — §5) rather than tolerated. The real impl's suite
> additionally covers the §7-mandated cross-tenant isolation case and asserts the unfiltered
> refusal as a passing guarantee.

## Proposed Jira (NOT posted — decision 4)

Comment on SOLUSDEV-138, then transition → Done:

> SYS-04 shipped on SOLUSDEV-69-lane-e-sol-systems. Real `SolSystems` (`agent/feeds.py`,
> `DbSolSystems`) implements all four feeds + the flywheel per W0-07 by assembling
> `load_neighborhood`/`to_graph_context`, `TelemetryPlumbing`, and SYS-02 retrieval — uniform
> in-query project scoping, degree clamped at 2, `domains` honored in-query,
> `budget.max_entities` sub-sampling with `truncated`. `FakeSolSystems` demoted to a test
> double with a src-wide banishment ratchet. Acceptance verified live: a turn on the
> 243-entity Onshape project cited real Kinova Gen3 parts through 4 successful tool calls,
> zero fixture fictions. Cross-tenant isolation tested per feed; SOL-01 core contract test
> passes against fake AND real.
