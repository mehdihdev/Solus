# SOLUSDEV-260 Phase 1 execution plan

User approved continuation after Phase 0. Begin implementation after Phase 0b commit.
Governing docs read: ADR-027/034, hardware architecture/API/wireflow, workspace
retention rules and hardware-config storage schema. No contract/schema changes.

## Tasks and ownership

1. Adapter preservation: `hardware/runtime.py`, `hardware/migration.py`,
   `hardware/store.py` under `packages/api/src/solus_api/`; tests
   `packages/api/tests/test_hardware_config_migration.py` and new
   `packages/api/tests/test_hardware_runtime_roundtrip.py`.
2. Existing-target detection, after task 1: `hardware/detect.py` and
   `packages/api/tests/test_hardware_roundtrip_regression.py`.
3. Root evidence: `docs/qa/PHASE1_SOLUSDEV-260.md`; independent reviewers read only.

One worker executes adapter/test changes together; detection consumes the stable
adapter sequentially. Root writes manifests before implementation. Tests first,
then bounded implementation, focused PostgreSQL tests and live rollback reproduction,
then code/Python/security reviews and phase commit.

## Required behavior

- Owner excluded from its own component targets, including bus self-references.
- Owner component firmware is returned as v1 top-level firmware with provenance.
- Typed helpers reduce runtime complexity while preserving enabled binding filters,
  project/live/CONFIG scoping and bus provenance reindexing.
- Split owner-key collisions merge component data into the owner document; preserve
  connection fields. Equal/disjoint firmware copies merge; conflicting values fail
  closed. Preserve effective provenance, including explicit component lifecycle.
- A v1 aggregate has no representation for owner calibration/limits/telemetry or
  lifecycle. Compatibility writes must preserve these existing v2-only owner fields
  in the store adapter instead of clearing them. Add an explicit regression case;
  do not falsely claim arbitrary v2-to-v1 conversion is lossless.
- Detection adds accepted nonconflicting endpoints to the saved runtime document,
  retaining prior bindings, components, firmware and disambiguation. Preserve
  existing effective provenance; do not flatten it into a new artificial layer.
  Conflicting saved identity/protocol requires explicit review and rolls back.
  Leave generic merge_layers list-replacement semantics unchanged.

## Tests and invariant

Retain the four Phase 0 RED route regressions plus control. Test owner collision,
firmware conflict refusal, existing detection identity/protocol conflict rollback,
and preservation of owner v2-only component data. Run split then runtime resolution
against every existing `tests/fixtures/hardware/*.json` document on PostgreSQL.
Compare every portable value and effective provenance at each valued leaf.

Raw paths/last_seen_path cannot satisfy literal equality: governing privacy rules
require their removal/tokenization. Compare approved portable transformations and
record that qualification. Provenance prefix layout can differ while attribution
at every leaf stays equal. Self-owner malformed input is tested separately because
the owner must no longer appear in parts. Source-token derivation remains unchanged
until Phases 2/3.

Full later-phase test/lint debt remains tracked in Phase 0. No Phase 2 data revision,
constraint or Phase 3 unrelated repair is included here.
