# SOLUSDEV-251 completion on SOLUSDEV-260

Status: implementation integrated and Phase 3 verification passed. API: 4852
passed/7 skipped plus one later focused regression; desktop: 3178 executed cases
verified plus six later scope regressions/one skipped; Live Bench: 476 passed;
companion: 258 passed. Static checks and live rollback verification passed.
This report covers 251 only. SOL and Workspace merge verification belongs to the
subsequent phases of SOLUSDEV-260 and is not claimed here.

## Scope and governing design

The supplied pre-merge review and hardware onboarding architecture, hardware API,
workspace/solus-folder architecture, workspace and hardware wireflows, hardware
configuration schema and private local-state contract govern these changes.
See `PHASE0_SOLUSDEV-260.md`, `PHASE2_SOLUSDEV-260.md`,
`PLAN_PHASE3_SOLUSDEV-260.md` and `PHASE3_SOLUSDEV-260.md` for evidence and decisions.

- A0: PostgreSQL preflight classified the fresh live database and historical fixture
  cases. No unhandled legacy rows existed in the live database. Snapshots preceded
  migration; the graph retained its six legitimate nodes and five relations.
- A1: owner/component collision fixed at split and runtime assembly. Firmware and
  connection identity survive promote, PUT, detect confirm and library import.
  Per-entity reads validate indexed identity/version and live graph authority.
- A2: separate backfill and constraint revisions applied in order. Nested parts,
  duplicate/conflicting copies, detached retention, provenance and rerun behavior
  are covered by real PostgreSQL fixtures. Single head is `a26000000003`.
- A3: account/project-scoped local reader, source IPC controls and explicit migrated
  reference relinking implemented. Renderer CONFIG editing uses v2 routes and
  expected versions. Session paths verify local sources and use ephemeral USB hints.
- A4: lifecycle release, pure reads, missing/deleted/conflict behavior, static checks,
  reviewer fixes and QA walkthrough implemented. Final suite/live results are in
  the Phase 3 evidence report. No A1/A2 manifests existed under the legacy
  `.claude/state/ownership/` location to remove.

## Decisions and practical limits

The user approved explicit picker relinking because legacy paths contain no digest
and migration cannot read private files. One opaque reference is minted per
project/exact legacy string; a real picker verifies bytes locally. Existing aliases
remain valid. No shared calibration values or provenance are silently replaced.

Configuration is created on first PUT, not GET. The renderer uses optimistic
concurrency; the legacy unversioned compatibility PUT is retained. Arbitrary raw
`repo_root` values are refused because they confer no local filesystem authority.
Broader parser/proposal work remains B2; this phase verifies existing calibration
references before opening saved hardware sessions.

The actual adapters are enumerated, but physical roles are tentative and telemetry
is not yet verified. Native picker/relink and GitHub/Onshape connection require the
running Electron app; fixture tests are not represented as native live checks.
The fresh live database has no historical configs, so historical migration cases
are verified on PostgreSQL fixtures, not fabricated user data.

Standalone creation, absent-CONFIG first save and connection-owner part sessions
are API-only; the current renderer edits existing CONFIG entries. The QA file
provides concrete fixture requests instead of implying unavailable UI controls.

Full walkthrough: `COWORK_QA_SOLUSDEV-251.md`. No push, MR, main modification or
other-worktree operation was performed. Subsequent 253–256 work should branch from
260, or from main after 260 is merged by a human.
