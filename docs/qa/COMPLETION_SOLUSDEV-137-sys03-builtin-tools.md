# Completion — SOLUSDEV-137 (SYS-03): builtin tools over the real subsystems

**Status: tools half DONE; error-capture half BLOCKED on ERR-01 (LANE I) — stated plainly.**

## What was built

- **`agent/tools/builtin.py`** — `run_checkers`, `query_graph`, `retrieve_errors`,
  `get_telemetry` as W0-04 tools, following the `get_entity` factory pattern: thin closures
  over the real `SolSystems` (SYS-04's `DbSolSystems`), so the tool layer and `build_context`
  share ONE data path per subsystem and cannot drift.
  - `query_graph(entity_ids, degree≤2, kinds?, domains?)` → `get_graph_context` (200-entity
    budget matching `plan_query`).
  - `get_telemetry(duration_seconds, signals?)` → the live telemetry plumbing; empty buffer →
    `windows: []`, honest.
  - `retrieve_errors(query, k≤20)` → `get_error_history` against the REAL `error_solution`
    store (built by SYS-02) with `RetrievalFilter(project_id=…)` bound by Solus code.
  - `run_checkers(entity_ids)` → 2-hop graph slice → **CHK-01's real rules**
    (`DEFAULT_CHECKERS` via `checkers/interface.py::run_checkers`) with the sanctioned empty
    `FingerprintOutput` (the `impact/consequences.py` production precedent); returns
    `{"warnings": […sorted most-severe first…], "truncated": …}` per agent-tool.md §3.
- **`build_sol_registry(systems=…)`** — one new keyword; registration is function-local
  (house pattern) so the reasoning import graph grows the checker dependency only when wired.
  The bridge-tool block was extracted to `_register_bridge_tools` (complexity limit), behavior
  identical.
- **All three SOL routes** (`GET /tools`, `POST …/messages`, `POST /confirmations/{id}`) pass
  the app's `SolSystemsDep`, so the model's tool set includes the four builtins everywhere.

## Security invariants preserved (verified by tests)

- `project_id` is bound in each closure at registration and **absent from every params
  schema** (`additionalProperties: false` throughout) — ingested content cannot alter scope.
- All four tools are reads: `requires_confirmation=False`, default per-call timeout; the
  destructive gate and its ratchets are untouched — `tests/test_sol_runtime.py` (incl.
  `test_only_the_gated_dispatcher_reaches_registry_invoke`) passes unchanged, as does the
  red-team suite.
- **Never-raises proven per tool**: a subsystem raising `RuntimeError` surfaces as
  `ToolResult(ok=False)` with a structured `ToolError` through the gated dispatch, and the
  failure message does not leak into `value`.
- UUID args are re-validated in the handler (`INVALID_ARGS`, not a crash) since jsonschema's
  `format: "uuid"` is annotation-only.
- `Warning.message`/`evidence` are untrusted connector strings; they re-enter the model only
  through the existing `prompt.contain_result` fencing.

## Test coverage (`tests/test_builtin.py`, invoked through `build_dispatch` — the reasoning

loop's actual execution layer)

Registration + schema discipline; `query_graph` neighborhood correctness; `get_telemetry`
window summary + honest empty; `retrieve_errors` real-store hit with cross-tenant seeding
(only the caller's project's row returned); **`run_checkers` fires a real CHK-01 rule** on the
wrong-op-amp seeded bug (LM358-class amp driving a 10× load — `OpAmpMismatchChecker` warning
surfaced) and returns zero warnings on an empty slice; the per-tool never-raises invariant.

## BLOCKED scope — reported, not built

The acceptance line "error-capture pipeline runs in the backend and feeds the error store" is
**ERR-01 (SOLUSDEV-127, LANE I, unbuilt)**. The store itself exists (SYS-02) and
`retrieve_errors` runs against it honestly — empty results until capture lands. Building the
capture pipeline here would reach into LANE I's in-flight scope; deliberately not done.

## Proposed Jira (NOT posted — decision 4)

Comment on SOLUSDEV-137 (suggest: leave in progress or mark Done-with-note, your call given
the ERR-01 dependency):

> Tools half shipped on SOLUSDEV-69-lane-e-sol-systems: run_checkers / query_graph /
> retrieve_errors / get_telemetry registered as W0-04 tools wrapping the real SYS-04 feeds
> and CHK-01 rules, invoked through the gated execution layer with project scope bound by
> Solus code (never a model arg). Never-raises invariant tested per tool; destructive-gate
> ratchets unchanged. The error-capture-pipeline half is blocked on ERR-01 (SOLUSDEV-127,
> LANE I, unbuilt); retrieve_errors degrades honestly (empty) until capture lands.
