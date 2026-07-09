# Completion Report — SOLUS-W0-04: Agent-Tool Interface Contract

**Branch:** `SOLUSDEV-72-shared-dev-models` (continued alongside W0-01/02/03, per the
established Week-0 pattern — confirmed with the founders).
**Status:** Complete, fully integrated, validation-green. Ready for human review → MR.

---

## What was built

A Week-0 shared contract (ADR-028) — the tool-calling spine the SOL Agent uses to invoke
capabilities uniformly and safely — plus a working reference implementation and the
`artifacts` table for large-data references.

**`packages/api/src/solus_api/agent/tools/`** (new package, standalone like `orchestration/`):

- `shapes.py` — the four envelope shapes (`ToolDescriptor`, `ToolCall`, `ToolResult`,
  `ToolError`) + `ArtifactRef` + `ToolErrorCode`. Frozen Pydantic v2; `ToolResult` enforces
  the ok/value/error invariant via a model validator.
- `tool.py` — `Tool` (Protocol: `descriptor` property + async `invoke`), `ToolException`
  (the typed failure signal), `InProcessTool` (the v1 kind).
- `registry.py` — `ToolRegistry` (register / list / invoke). `invoke()` runs the safety
  sequence and **never raises**: unknown tool → NOT_FOUND, bad args → INVALID_ARGS (JSON
  Schema validation with format-checking), timeout → TIMEOUT, `ToolException` → its code,
  any other exception (incl. a non-dict return) → TOOL_ERROR with a generic message and the
  traceback logged server-side only.
- `get_entity.py` — the reference tool, proving the contract end to end against `graph_entity`.

**W0-01 addendum (data model):**

- `models.py` — `ArtifactScope` / `ArtifactStorage` enums, the `Artifact` model, and the pure
  `artifact_is_accessible(...)` rule (PRIVATE → creator only; PROJECT → project members).
- `schemas.py` — `ArtifactRead`.
- `migrations/versions/344b7841f6d3_add_artifacts_table.py` — new migration,
  `down_revision = 7ea820a98068`; the original W0-01 migration is untouched.

**Docs:** `docs/contracts/agent-tool.md` (the contract) and `docs/qa/COWORK_QA_agent-tool.md`
(the QA plan).

**Dependency:** `jsonschema>=4.20` + `types-jsonschema>=4.20` added to `packages/api`.

---

## Governing docs consulted

DECISIONS.md (ADR-010 agent-as-orchestrator, ADR-027 graph/soft-delete conventions, ADR-028
Week-0 human-owned contracts), CLAUDE.md §7 (model-orchestration security), the sibling W0-03
contract (`docs/contracts/model-orchestration.md` + `orchestration/`) for structure/style, and
the existing `models.py` / `schemas.py` / migration idioms. No architecture diagram or API-route
plan governs this contract module (it is standalone and mounts no HTTP route).

---

## Audit-first result

Ticket was audit-first. **No existing `agent/` or `tools/` code** existed (only an empty
`reasoning/agent/.gitkeep`) — a greenfield build, not an overwrite. Full audit table in the
plan; no pause-for-divergence was needed.

---

## Test coverage

- **31 new tests** across `test_shapes.py`, `test_tool.py`, `test_registry.py`,
  `test_get_entity.py`, `test_artifacts.py`. Full suite: **151 passed**, mypy strict clean
  (38 files), ruff clean.
- Acceptance criteria proven: registry lists tools; valid id → `ok=true` + curated value (no
  embedding); missing id → `ok=false, NOT_FOUND`; bad/non-uuid args → `INVALID_ARGS`; unknown
  tool → `NOT_FOUND`; **out-of-scope entity → NOT_FOUND** (tenant isolation); soft-deleted →
  NOT_FOUND; scope-smuggle via an extra `project_id` arg → `INVALID_ARGS`; unexpected exception →
  `TOOL_ERROR` with no traceback leak; non-dict return → `TOOL_ERROR` (invoke never raises); the
  `artifact_is_accessible` truth table incl. the orphaned-creator case.
- Migration verified on a fresh DB: `upgrade head → downgrade base → upgrade head`, single head.

---

## Decisions made under delegated judgment

1. **`jsonschema` at the registry (confirmed with founders).** The registry validates each
   tool's raw `params` JSON Schema generically (cached Draft-2020-12 validator + format checker),
   so future MCP/remote tools — which supply raw schema over the wire, not a Pydantic model —
   validate uniformly. One new (ubiquitous) dependency; the alternative (a Pydantic model per
   tool) would weaken the cross-kind uniformity the contract exists for.
2. **`get_entity` is tenant-scoped by construction, not by model args.** The model-facing
   `params` is exactly `{entity_id}` (per the ticket); the caller's `project_id` scope is a
   constructor argument bound by Solus code (CLAUDE.md §7 — ingested content cannot alter team
   scope). Out-of-scope and missing ids both return NOT_FOUND (no cross-tenant existence oracle).
3. **Registry is a pure dispatcher — no auth, no events.** Tool-side authorization lives in tool
   code; `agent.tool_invoked` events are emitted by the SOL consumer that holds the request
   user/session, not threaded through the pure registry. Documented in the contract §7.
4. **Enum placement:** `ArtifactScope`/`ArtifactStorage` are DB-column enums → `models.py` (single
   source of truth; `ArtifactRef` imports `ArtifactStorage`). `ToolErrorCode` is a pure contract
   enum → the tools package.
5. **Ponytail pass:** inlined the single-use `_timeout_for` helper; kept `_failure` (4 call sites)
   and `_serialize` (documents the curated `returns` projection). Diff is contract surface, not bloat.

---

## Phase-4 review outcomes

Both mandatory reviews ran on the integrated diff and **passed** (0 CRITICAL / 0 HIGH):

- **Code review — APPROVE.** One LOW (a tautological `model_fields_set` assertion) — **fixed**
  (now asserts real optionality defaults).
- **Security review — PASS.** All seven §7 properties hold (tenant isolation, no-leak,
  never-raises, input validation, artifact access, no string-SQL/secrets/eval). Findings addressed:
  - **L1 (fixed)** — added the scope-smuggle regression test (extra `project_id` arg → INVALID_ARGS).
  - **L2 (fixed)** — replaced the DSN-shaped decoy in the leak test with an obviously-fake sentinel.
  - **M2 + L3 (fixed, doc)** — contract §6 now states ingested `value` fields are DATA-not-
    instructions (delimited by the consuming SOL context layer; injection red-team is that ticket's
    requirement) and that the registry must be built fresh per request.

---

## Founder-approved contract addition (M1 — implemented, ADR-028)

- **M1 — `requires_confirmation` on `ToolDescriptor`.** The security review recommended a uniform
  destructive-action marker; a founder approved adding it, so it is **implemented** (not just
  flagged). `ToolDescriptor.requires_confirmation: bool = False`. It is **declarative metadata**:
  the orchestrator reads it and obtains explicit user confirmation (with the concrete action shown)
  **before it dispatches** the `ToolCall`, so §7's confirmation gate is enforced centrally rather
  than hand-rolled per tool. The registry stays a pure dispatcher and does not read the flag —
  confirmation is a pre-dispatch, human-in-the-loop concern owned by the SOL-loop ticket. Documented
  in contract §3/§6/§10; covered by `test_descriptor_can_flag_a_destructive_tool_for_confirmation`.
  `get_entity` is read-only, so it takes the safe `false` default.

---

## Deviations / open concerns

- **New dependency** `jsonschema` (+ stubs) — see delegated decision 1. Flagged because a shared
  contract gaining a dependency is worth a human's eye.
- **Test-infra fragility (pre-existing, not introduced here):** the H10 Stop gate ran `pytest`
  against the shared `solus_test` DB while the two review subagents were also running `pytest`
  against it; the conftest isolates tests by un-locked `TRUNCATE`, so concurrent runs flake
  unrelated tests (2 `test_invites.py` failures during that window). Re-running the full suite on a
  dedicated DB is **green (151 passed)**; this diff is unaffected. Worth a future hook/conftest
  hardening (per-run DB or a lock), but out of scope here.

---

## Human handoff steps

1. Review the integrated feature branch and this report.
2. Decide M1 (`requires_confirmation` on `ToolDescriptor`).
3. `git add` / commit / push, open the MR in GitLab, merge to main after review.
4. Run the Cowork QA pass (`docs/qa/COWORK_QA_agent-tool.md`).
