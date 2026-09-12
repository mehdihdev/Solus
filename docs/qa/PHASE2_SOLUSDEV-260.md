# SOLUSDEV-260 Phase 2 — data migration and constraints

Completed after Phase 1 commit `258b02f`. User explicitly authorized continuing
Phases 2–6 and approved explicit relinking for legacy private files.

## Governing design and execution

Read ADR-027/034, hardware architecture/API/wireflow and hardware-config schema.
One worker owns the migration-specific helper, backfill revision `a26000000002`,
subsequent constraints revision `a26000000003`, migration PostgreSQL fixtures/tests,
and strict subject/version reads. Root owns source-token extraction and its tests,
preflight/snapshot/live application and evidence. Independent reviews follow the
fixture run, before live application. No existing migration is edited.

The backfill validates the complete plan before writes. Conflicting values or
provenance, ambiguous graph identity and foreign references abort the transaction.
Identical duplicates retain soft-deleted history; existing identities and timestamps
remain. Extracted components gain independent entries; detached live parts survive
removed owners. Constraints follow successful backfill. Irrepresentable downgrade
fails explicitly; the private snapshot is the recovery point.

## Approved relinking interpretation

Legacy paths have no file-content digest and must not be read during migration.
The user approved one opaque reference per project/file, explicitly relinked by the
local picker with a newly verified local digest. A private source string is mapped
to `source:<UUIDv5(project UUID, exact legacy source string)>`, shared by all parts
and owners citing it in that project. No path canonicalization guesses another
machine's layout. Different spellings may need separate explicit relinks.

The opaque reference identifies evidence; it does not authorize reading a path and
is not proof of selected-file content. In Phase 3, the authenticated picker can
bind a migrated reference to the user-selected file under that account only.
Changed known digests require review. This intentionally replaces the impossible
requirement to derive a missing file-content digest during migration; no digest is
invented. The existing local-state document shape remains unchanged.

## Initial preflight refresh

Database `solus` at 127.0.0.1:5432, this task's `solusdev-260-db` container and
`solus_pgdata` volume: one project, six graph entities, zero CONFIG entries and zero
integration connections. Current revision `a25100000001`. All configuration classes
remain empty. Re-inventory and take a new validated snapshot immediately before
applying the tested revisions. Empty live rows do not prove historical migration;
that evidence must come from PostgreSQL fixtures.

## Verification and live application

- PostgreSQL migration/constraint suite: **27 passed**, 69.47 seconds. Covers nested
  extraction, firmware, provenance, identical/conflicting copies, existing v2 state,
  deleted owners/parts and existing empty history, foreign/ambiguous graph references,
  sanitized failures, repeatability, refused downgrade, constraints and actual
  writer-lock/concurrent-insert behavior. Log: `/tmp/solus260-phase2-green.log`.
- Compatibility and source suite: **38 passed**, 33.48 seconds. Log:
  `/tmp/solus260-phase2-compat.log`. The source expectation was deliberately updated
  to the approved project namespace; no field-preservation assertion was removed.
- Changed migration/store/test files pass ruff and strict mypy. Whole-package
  baseline lint/type issues remain assigned to Phase 3, not claimed green here.
- Independent code/Python/database and security reviews passed after all retention,
  shared-node, ownership, unrelated-edge and private-error findings were fixed.
- Stopped only this task's verified API PID 2126353 before the snapshot/apply.
  Snapshot `/tmp/solus260-snapshots/phase2-before-backfill.dump` was validated with
  `pg_restore --list`; SHA-256
  `76ea000ebbe92eae1c4910f655c6a4c93076de4807bff69f1ade129cf71abc02`.
- Applied `a26000000002` then `a26000000003` to this task's `solus` database.
  `alembic current` and `heads` both report the single `a26000000003` head.
- A fully rolled-back fixture in that live database proved both
  `uq_solus_config_subject_live` and `ck_solus_config_subject` reject invalid writes.
  Counts before/after remain **6 graph entities, 5 edges, 0 CONFIG entries**.
  The empty live dataset does not substitute for the historical PostgreSQL fixtures.
- Restarted the task API on port 8000 (PID 2267053); readiness checked after startup.

The payload-identity lookup fallback and version coalesces are removed. Every
production compatibility split passes project scope explicitly. No private source
file was read, no account data was deleted, and no other worktree was modified.
