# SOLUSDEV-260 Phase 1 — configuration preservation

Implementation follows `PLAN_PHASE1_SOLUSDEV-260.md`; Phase 0b is committed as
`c4e66a8`. Phase 1 verification is complete; later phases remain outstanding.

## Before-fix live reproduction

Re-ran the owner-as-part reproduction against this checkout's live PostgreSQL
`solus` database using a rollback-only transaction. The fixture created its own
team/project, robot and sensor, saved identity/protocol/bus mapping, firmware and
user disambiguation, then resolved runtime configuration. It failed:
`AssertionError: Owner appears in its parts`.

The transaction rolled back in a finally block; direct before/after graph counts
both equal 6 entities and 5 edges. No fixture node or configuration remained.
Harness: `/tmp/solus260-phase1-live.py`. This is a service-level PostgreSQL
reproduction, distinct from authenticated route tests and physical hardware QA.

## Scope and invariant

Preserve portable values and effective provenance across the existing legacy
fixtures. Private paths/port hints are intentionally removed or tokenized per
ADR-034; raw path equality is not a valid shared-state invariant. The owner never
appears in its own parts. Owner firmware is represented by the v1 top-level field;
existing owner component values that v1 cannot represent are preserved at the
compatibility write boundary.

## Final verification

- **74 passed in 43.65 seconds** across hardware config, config migration, runtime
  roundtrip, route regression, ownership and operations suites on isolated
  `solus_test_436a6e18_phase1`. Log: `/tmp/solus260-phase1-verification.log`.
- The final specific-binding test refinement passed separately: 1 passed in
  2.25 seconds on `solus_test_436a6e18_detect`.
- Ruff lint/format and strict mypy pass for all seven changed Python files.
- Code/Python and security reviewers passed the complete phase diff.
- All three existing hardware fixture files remain unchanged. Roundtrip checks
  compare every portable value and effective provenance, with approved privacy
  transformations explicitly accounted for.

Only the session-owned API PID 1987161 was gracefully restarted after verifying
its command and checkout. The new API PID 2126353 listens on the same 8000 port;
`/readyz` returns database ok and Redis/queue configured. Authenticated browser
requests return 200 and the workspace remains 6 entities / 5 relations / 0 sources.
The root .env and other worktrees were not edited.

The original API baseline failures outside this phase are still tracked for
Phase 3. No data migration, constraints, 252/250 merge or physical hardware gate is
claimed complete. Phase 2 next requires fresh preflight/snapshot, PostgreSQL fixture
migration proof, data revision, then constraint revision.

Detection conflict tests reproduced four additional unsafe successes: a changed
transport identity, changed driver, changed protocol parameter, or occupied bus
address each returned HTTP 201 instead of refusing the unreviewed replacement.
All four were RED on isolated `solus_test_436a6e18_detect` in 9.40 seconds.
Log: `/tmp/solus260-detect-red.log`. Preservation coverage now also asserts the
new accepted binding is present and saved effective provenance remains unchanged.

## Implemented preservation boundaries

Runtime assembly excludes the owner, returns its firmware at the v1 top level,
and preserves effective provenance. Typed helpers separate component loading and
active-bus assembly, clearing runtime's complexity/type findings. Legacy splitting
merges self-owner component data into the owner rather than replacing connection
fields; contradictory firmware values fail closed. Equal firmware values retain
explicit top-level firmware attribution. Null firmware values survive without
requiring provenance for an unvalued leaf.

The compatibility store preserves owner calibration/limits/telemetry/lifecycle
that v1 cannot represent, and preserves each child controller's independently owned
connection fields while updating its component. Existing-target detection appends
accepted bindings/components without replacing existing context or flattening its
provenance. Changed saved identity/protocol or occupied addresses return
`409 proposal_changed` and leave the transaction unchanged.

Two incomplete representations deliberately require review:

- An unmigrated legacy document embedding its owner as a part returns
  `409 config_upgrade_required`; it is not silently normalized with field loss.
- A participating configuration with live disabled bindings returns the same code
  on compatibility writes. Runtime hides those bindings operationally; writing that
  projection would erase evidence or re-enable a stale endpoint. Use the explicit
  versioned v2 configuration path for a reviewed change instead.

Independent code/Python and security reviews passed after regressions reproduced
and fixes closed both disabled-binding evidence loss and nested-controller
connection loss. Root also corrected the detection test to select the intended
bound part explicitly. No confirmation gate, tenant boundary or private-path rule
was weakened.

## Live after-fix check

The same `/tmp/solus260-phase1-live.py` reproduction now passes: owner is absent
from parts, and promotion preserves identity, protocol, bus map, disambiguation and
owner component. Its finally rollback again leaves exactly 6 entities and 5 edges.
This does not claim physical device verification or a migrated historical dataset.
