# Completion Report — SOLUSDEV-115 / SOLUS-CHK-01: Compatibility Checkers Core

**Branch:** `SOLUSDEV-115-compatibility-checkers-core` (local commits only — not pushed).
**Status:** Implementation complete, fully verified, ready for human review → MR.

## What was built

The cross-domain catch logic — pure-function rules over the linked graph that flag integration
bugs spanning domains — implemented against the checker contract already staged on this branch.

- **Three rules** (`packages/api/src/solus_api/checkers/core.py`):
  - `op_amp_mismatch` — walks `drives` edges; flags an op-amp unfit for its load's gain-bandwidth
    (WARNING), output-current, or supply-voltage range (CRITICAL). One warning per bad pairing,
    aggregating failed dimensions at the worst severity.
  - `sensor_frequency_conflict` — walks `reads_from` (code→sensor); flags under-sampling below the
    Nyquist floor (WARNING, spans code+electrical), over-polling stale reads (WARNING), and bus
    saturation (CRITICAL, electrical).
  - `power_compatibility` — walks `powers` (supply→loads); flags load voltage outside the supply
    tolerance band (CRITICAL) and summed current draw exceeding the supply rating (CRITICAL).
- **`GraphView` traversal helper** (`traversal.py`) — indexes the graph once per check, resolves
  `edges_of_type` to `(src, dst)` pairs, drops dangling edges, dedupes duplicate edges.
- **Seeded-bug eval** (`tests/test_checker_graphs.py` + `tests/fixtures/checker_graphs.py`) —
  4 seeded bugs + 6 clean controls → **catch rate 100% (4/4), false-positive rate 0% (0/6)**.
- **Contract doc** `docs/contracts/checker-interface.md` (was referenced by the module docstrings
  but did not exist — now written).
- **Cowork QA** `docs/qa/COWORK_QA_compatibility_checkers_core.md`.

## Governing docs consulted (CLAUDE.md §3 pre-work check)

DECISIONS.md (**ADR-003** checkers are pure/stateless, graph-in/warnings-out, heavy runs are jobs;
ADR-001 graph-centric; ADR-013 the checker library is autocomplete/proving/part-compat; **ADR-028**
`packages/contracts/` is human-owned), CLAUDE.md §7 (untrusted connector `attrs`), §9 (shared
contracts). No `docs/architecture` / `docs/api` / `docs/wireflows` artifact governs this backend
library (no route/UI in this ticket). No new ADR was needed.

## TDD & verification

- Tests written first per rule (RED confirmed), then implemented to green.
- **Full API suite: 394 passed** (1 pre-existing, unrelated JWT key-length warning in
  `test_security.py`). Checker files alone: 53 tests. `ruff` clean, `mypy` clean.
- **Code review** (code-reviewer) and **security review** (security-reviewer) both run in Phase 4.
  Security initially returned **FAIL**; all findings fixed; security re-review verdict **PASS**.

### Security findings addressed (CLAUDE.md §7)

Both reviewers converged on: untrusted `attrs` could carry `nan`/`inf`/negative values that invert
the skip-logic — fabricating spurious CRITICALs _and_ suppressing real ones. Fixes:

- `_as_float` rejects non-finite (`math.isfinite`); new `attr_nonneg_float` rejects negatives, used
  for **all** physical reads in the rules.
- Op-amp rule skips inverted `[v_min, v_max]` bounds; traversal dedupes duplicate edges.
- `Warning.message`/`evidence` documented as **untrusted** — mitigation belongs to the SOL Agent
  (delimit in prompt assembly) and the CHK-03/04 UI (HTML-escape), not this pure layer.
- New eval control `malicious_attrs` + an inert-carriage test lock in that a payload-laden entity
  name is carried as plain data, never executed, and produces no false positive.

## Decisions made under delegated judgment

- **Contract staged in `solus-api`, not `packages/contracts/`** — CLAUDE.md §9 lists the checker
  interface as a shared contract but ADR-028 makes `packages/contracts/` human-owned. Mirrored the
  connector-contract staging pattern already on this branch; flagged for human promotion (locked
  with the CHK-03/04 warning UI) in the contract doc.
- **Roles inferred from `relation_type`, not gated on `part_class`** — maximizes catch on graphs a
  connector labelled with edges but not `part_class`; a comparison only runs when its specific
  attributes are present and valid. `part_class` kept as advisory metadata. (Documented.)
- **Warning granularity differs by rule** (op-amp aggregates per pairing; frequency/power emit one
  per distinct conflict) — intentional, documented per rule. Acknowledged as a LOW consistency
  note, no change.

## Open items for the human

1. **Push / MR / merge** — human territory. Two local commits on the feature branch.
2. **Promote the contract** to `packages/contracts/`, locked with CHK-03/04's `Warning`-UI shape.
3. **Ownership manifest** `.claude/state/ownership/SOLUSDEV-115-checkers.list` was reconciled to the
   actual filenames (the planned `test_checkers_*` names conflict with the repo's `test_<module>.py`
   TDD-hook convention; the Cowork QA lives under `docs/qa/`).
4. **Jira** SOLUSDEV-115 is still in _Feature Planning_; not transitioned (outward-facing — left for
   a human, or say the word and I'll transition it / post a summary comment).
