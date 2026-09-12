# SOLUSDEV-251 — pre-merge review

**Date:** 2026-09-08 · **Branch:** `SOLUSDEV-251-hardware-ownership-config` (`0d13548`) · **Base:** `origin/main` (`3a90ab6`)

**Status: do not merge as-is.** One defect is a silent destructive write reachable from routes that
return 200. It is reachable from this branch alone, not only through the sibling branches.

This began as a read-only assessment. Lint and type-checking were subsequently run and their results
are recorded in §3.9. Everything else is a code trace with file references, reproduced against no
live database, because PostgreSQL is not running in this environment and the suite therefore could
not execute. The two most severe findings were traced from both ends independently. Items marked
**UNVERIFIED** need a test before they are treated as fact.

**Scope of the branch reviewed:** 38 files, ~4,957 insertions and 772 deletions against
`origin/main`. This excludes the SOLUSDEV-249 work, which the branch merged in at `52a876c` and
which is already on `origin/main`.

---

## 1. What the plan asked for, and what is on the branch

`docs/qa/PLAN_workspace_hardware_redesign.md` makes 251 unit A of a five-ticket stack, with 253,
254, 255 and 256 each starting from the previous branch. Unit A has five tasks.

| Task | Scope                                                                    | State                                                                                                                             |
| ---- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| A0   | Performance baseline and migration preflight inventory                   | **Not started.** Neither `docs/qa/PERFORMANCE_SOLUSDEV-251_baseline.md` nor `docs/qa/MIGRATION_SOLUSDEV-251_preflight.md` exists. |
| A1   | Entity-owned configuration, ownership, migration, compatibility adapters | **Built**, with the defects in §3.                                                                                                |
| A2   | Private hardware sources in desktop MAIN                                 | **Built**, and unreachable — see §5.                                                                                              |
| A3   | Integrate references, server-side local reader, regenerate typed clients | **Not started.** `hardware/local_sources.py` absent; renderer and `openapi.json` untouched.                                       |
| A4   | Verification and handoff                                                 | **Not started.** No completion report, no Cowork QA file.                                                                         |

The A1 and A2 ownership manifests are still installed under `.claude/state/ownership/`. Under the
plan's own rule a manifest is removed only once its task is integrated and verified, so the branch
is not at a handoff state by its own bookkeeping.

A1's manifest also claims files the branch never changed, including `detect.py`, `links.py`,
`library.py`, `library_router.py`, `services/physical_robots.py`, `routers/entities.py`,
`livebench/bench_router.py`, `graph/resolver.py`, and most of the existing tests it listed as
test-first targets. The consumers of the rewritten store were not updated and their tests were not
extended.

---

## 2. The ownership model is correct and worth keeping

This part of the design holds up and the implementation is careful.

- Configuration is keyed by graph entity ID. A part belongs to its project and may have no robot
  parent.
- Robot assignment is a separate `contains` edge. `assign_parent` in `hardware/ownership.py`
  soft-deletes the old edge and adds a new one; the part entity, its ID, its `external_ref`, its
  source identity and its configuration entry are untouched by a move.
- Provider-sourced entities are never rewritten. Convenience attributes are updated only when
  `part.origin == "manual"` and `source_id is None`.
- Concurrency is gated on both the part version and the expected parent, returning 409
  `ownership_conflict` with the current values.
- Stale controller bindings are disabled on every ownership change rather than deleted, which
  preserves the evidence.

The reviewed-operation layer in `hardware/operations.py` is also sound. Idempotency is scoped by
project and user, enforced by the `uq_hardware_operation_scope` unique constraint that the migration
does create, with a payload digest so a reused key carrying different content returns 409 rather
than replaying. `test_hardware_operations.py` covers this with a genuine four-way concurrent
request test.

Telemetry identity is preserved. `attach_part` still sets `external_ref` exactly as before, and
`graph/resolver.py` still resolves on that column, so the existing ingest path is not disturbed.

---

## 3. The migration is not sound

### 3.1 CRITICAL — a compatibility round trip erases a robot's connection configuration

**Files:** `packages/api/src/solus_api/hardware/runtime.py`, `packages/api/src/solus_api/hardware/migration.py`

`resolve_runtime_config` adds the robot to its own target set with `targets.add(entity_id)`, then
fills `components[part_id]` for every target whose stored document carries a `component`. A robot
that has firmware recorded therefore appears inside `parts` keyed by its own ID in the reconstructed
v1 aggregate.

`split_legacy_document` builds the owner document first and assigns it as `output[owner]`, then
iterates `portable["parts"]` and assigns `output[part_id]`. When `part_id == owner`, the second
assignment **replaces** the first. The surviving document contains only `component` and its
provenance. `identity`, `protocol`, `bus_map` and `disambiguated_by` are gone.

Any read-modify-write through the compatibility adapters therefore destroys the robot's transport
identity, driver and bus map:

- `PUT /hardware/robots/{robot_id}/config`
- `POST /hardware/robots/{robot_id}/parts/{part_id}/lifecycle`, via `promote` in `store.py`
- the detect confirm path in `detect.py`
- the library import path in `library_router.py`

All of these return 200. Nothing surfaces the loss.

**Precondition:** the robot's stored document must carry a `component`. The migration sets one only
when the legacy document had non-empty `firmware`. A robot with no firmware is not affected.

**Fix:** either exclude the owner from `components` in `resolve_runtime_config`, or make
`split_legacy_document` merge rather than overwrite when the part key equals the owner.

**Test owed:** promote a part's lifecycle on a firmware-bearing robot and assert `identity`,
`protocol` and `bus_map` survive.

### 3.2 HIGH — there is no data migration

The Alembic revision `a25100000001` is purely additive. It adds `configured_entity_id` and
`config_version` to `solus_entries`, one foreign key, and the `hardware_operations` table. It
performs no data transform.

`docs/schemas/hardware-config.md`, which this branch authored, requires the opposite: schema and
data migration as separate revisions, a preflight over live and historical config entries including
deleted robots, migration of valid entries in place, and a backfill of version and subject IDs.
None of that exists. There is no preflight, no `packages/api/tests/fixtures/hardware_migration/`
dataset, and no backfill.

Conversion is instead lazy and write-triggered. Until something writes, existing rows keep
`configured_entity_id` NULL and `config_version` 0. `_find_entry` compensates by also matching on
the payload's `robot_entity_id`, and version reads coalesce with `max(entry.config_version, 1)`, so
the omission is masked rather than fixed.

### 3.3 HIGH — the declared uniqueness and check constraints exist nowhere

`packages/api/src/solus_api/models.py` declares a partial unique index
`uq_solus_config_subject_live` over `(project_id, configured_entity_id)` and a check constraint
`ck_solus_config_subject`. Neither name appears in any migration. The test suite builds its schema
with `alembic upgrade head`, so both are absent in tests, dev and production alike.

`_find_entry` raising 409 on more than one row is the only duplicate protection, and it fails a read
rather than preventing the write. Note that adding the index later would still not constrain legacy
rows, because a NULL `configured_entity_id` is exempt from a partial unique index. The backfill in
§3.2 is a prerequisite for the constraint in this section.

Writes are serialized in practice: `put_entity_config` calls `lock_project`, which takes
`SELECT ... FOR UPDATE` on the project row. That closes the lost-update race, so this is a
defence-in-depth gap rather than an active one.

### 3.4 MEDIUM — legacy nested part configuration is invisible until the robot is re-saved

`read_entity_config` finds an entry by `configured_entity_id` or by the payload's `robot_entity_id`
or `entity_id`. A part whose configuration is still nested inside a legacy robot document matches
none of these, so the new per-entity read returns nothing for it. The runtime aggregate still works,
because `resolve_runtime_config` returns a stored v1 document unchanged, so drivers are unaffected.

### 3.5 MEDIUM — `device_path` becomes null in the session payload

The migration strips `identity.last_seen_path`, and `resolve_runtime_config` never restores it. Two
untouched call sites still read it when opening a session, in `hardware_router.py` and in
`livebench/bench_router.py`. Once a robot's config has been written through v2 even once, both
record `device_path: None`.

Removing the path from shared state is the correct direction. The replacement half, a local runner
that supplies the path from the machine-local bindings map, is A3 and is not built. **UNVERIFIED:**
whether the drivers can open the device from the serial number alone, in which case the impact is
cosmetic.

### 3.6 MEDIUM — a plain GET writes, and now takes a project-wide exclusive lock

`GET /hardware/robots/{robot_id}/config` calls `ensure_config` and commits, creating the entry on
first read. This behaviour is inherited from `origin/main`, not introduced here, but the plan's A1
row required that a pure GET not create or recreate config, and it was not fixed. The route also
carries no role check while its sibling PUT requires MEMBER.

251 does make it worse. On `origin/main` `ensure_config` took no lock and returned early when the
entry existed. It now calls `lock_project` unconditionally and then runs `resolve_runtime_config`,
which issues several further queries. Every read of a robot config now takes an exclusive row lock
on the project and serializes all hardware traffic for that project.

The new v2 route `GET /hardware/entities/{entity_id}/config` is correctly non-mutating and is
covered by `test_hardware_ownership.py`.

### 3.7 MEDIUM — a deleted robot's parts keep their endpoints claimed

`disable_part_bindings` has exactly one caller, `assign_parent`. Its own docstring claims it covers
robot removal, but the removal path in `services/physical_robots.py` soft-deletes the robot and its
containment edges without touching the `binds` edges this branch introduced.

The conflict query inside `synchronize_bindings` filters on the edge being live and enabled but does
not check whether the owning config entry or the part entity is deleted. A new configuration
claiming that device endpoint therefore receives 409 `binding_conflict`, with no API to clear it.
This repeats the failure shape already recorded against SOLUSDEV-250, where a retained part kept a
device bound and the server named a deleted UUID.

Note the asymmetry: `configured_endpoint_targets`, which reads bindings, does filter both
`SolusEntry.deleted_at` and `GraphEntity.deleted_at` correctly. That function has **no callers** and
is dead code today.

### 3.8 Test coverage against what the plan required

`test_hardware_config_migration.py` is 92 lines with two pure-function tests, neither of which
touches a database. The plan's A1 migration row lists roughly eleven required behaviours, including
duplicate and conflicting copies, detached retention, private-path redaction, rerun idempotency and
real PostgreSQL constraint and locking behaviour.

`test_hardware_ownership.py` and `test_hardware_operations.py` are genuine HTTP integration tests
and are good work. No new test asserts `external_ref` or telemetry resolution for the new creation
flow.

Four existing test files exercise the legacy config paths and were not modified, so they act as an
unmodified regression net over the rewritten store: `test_hardware_router.py`, `test_store.py`,
`test_library_router.py` and `test_bench_robot_provider.py`. **UNVERIFIED:** they were not run.

### 3.9 HIGH — the branch fails lint and type-checking

Confirmed by running the repository stop gate on 2026-09-08. This is not a prediction.

**ruff, 9 errors, 6 auto-fixable:**

| Rule | Location                                                             |
| ---- | -------------------------------------------------------------------- |
| E501 | `models.py` line 890                                                 |
| E501 | the Alembic revision, line 64                                        |
| F401 | unused `typing.Any` in `hardware/bindings.py`                        |
| F401 | unused `resolve_runtime_config` in `hardware/hardware_router.py`     |
| F401 | unused `sqlalchemy.orm.aliased` in `hardware/ownership.py`           |
| F401 | unused `SolusEntryKind` in `tests/test_hardware_ownership.py`        |
| I001 | unsorted import block, `hardware/hardware_router.py` lines 6 and 214 |
| C901 | `resolve_runtime_config` complexity 14, ceiling 10                   |

**mypy, 9 errors, all in files this branch changed:**

| Location                                                   | Error                                                                                                                                             |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/test_hardware_config_migration.py` lines 56, 57, 60 | seven `union-attr` errors dereferencing `PartConfig \| None`, `PartCalibration \| None`, `PartLimits \| None` and `str \| None` without narrowing |
| `hardware/store.py` line 292                               | `union-attr` on `dict[str, Any] \| None`                                                                                                          |
| `hardware/runtime.py` line 89                              | `var-annotated`, `active_bus` needs a type annotation                                                                                             |

Two of these findings corroborate defects recorded above. The unused `resolve_runtime_config`
import supports §3.7, where the binding read path is unwired. The `store.py:292` union error is on
the `previous.payload.get("schema_version")` guard inside `put_config`, which is the same function
carrying the §3.1 blocker.

The C901 finding sits on `resolve_runtime_config`, the function at the centre of §3.1. Refactor it
as part of that fix rather than separately, or the work will be done twice.

---

## 4. Effect on SOLUSDEV-250 and SOLUSDEV-252

Neither branch is merged. Both are one commit behind `origin/main` independently of 251 and each
owes a merge of the SOLUSDEV-249 work regardless. **Only 251 adds an Alembic revision, so there is
no multiple-heads risk.**

|                          | 250 | 252 |
| ------------------------ | --- | --- |
| Overlapping files        | 6   | 4   |
| Predicted conflict hunks | 10  | 5   |
| Semantic breakages       | 7   | 5   |

251's route surface is purely additive. Every legacy handler body is unchanged and the new routes
are inserted above them, so `hardware_router.py` merges clean against 250 despite both editing it.
The risk is semantic and lives in `store.py`.

### SOLUSDEV-250

1. **HIGH — duplicate rows in the unassigned panel.** 251 removed the `source_id IS NOT NULL`
   predicate from `unassigned_parts_stmt`, so the endpoint now returns manual and retained parts as
   well. The 250 panel already fetches those from a second endpoint and will render each retained
   part twice. Its docstring in `store.py` still describes the old behaviour.
2. **MEDIUM — unhandled error codes.** `put_config` can now return 404 when a document names a
   deleted part, and 409 on a version conflict. Neither has a branch in 250's error mapping.
3. **MEDIUM — `device_path` null**, per §3.5.
4. **Conflicts are documentation.** Five doc files, ten hunks, several over a hundred lines per
   side, with sections renumbered. This is the bulk of the work and no tooling helps.
5. Stale `openapi.json` and `schema.ts` need regenerating.
6. `test_hardware_attach.py::test_unassigned_lists_connector_parts_not_owned_by_a_robot` asserts an
   exact set against the statement 251 changed, and will need updating.

### SOLUSDEV-252

252 modifies no `hardware/` file. Its entire exposure is through importing the rewritten modules
from new SOL agent code.

1. **CRITICAL — `agent/tools/make_diagram.py` breaks statically and at runtime.** `config_of`
   widened its return type from `HardwareConfig` to `HardwareConfig | EntityHardwareConfig`.
   `_robot_config` still annotates the v1 model, so **mypy fails for the whole `packages/api`
   package**, taking the type-check and stop gates red. At runtime the value flows into a builder
   that dereferences `parts` and `robot_entity_id`, neither of which exists on the v2 model, and the
   surrounding `except Exception` wraps only the `config_of` call, not the builder.
   _Fix:_ call `resolve_runtime_config`, or narrow with `isinstance`.
2. **CRITICAL — `agent/tools/solus_tools.py` destroys configs behind a consent card.** Its
   `set_field` tool reads through `ensure_config`, mutates one leaf, and writes through
   `put_config`. That is exactly the round trip in §3.1. The consent card renders a single
   innocuous field change from `field_preview`, so the user approves a one-field edit and gets a
   wiped configuration. This is the worst outcome in the analysis precisely because it looks
   reviewed.
3. **LOW — dead v1 mapping.** `services/solus_config.py` maps the HARDWARE section to the v1
   `HardwareConfig`, which rejects a v2 payload. Its only caller guards HARDWARE out first, so it is
   unreachable today and will bite whoever removes that guard.
4. **Trivial conflicts.** One declaration block in `apps/desktop/src/main/index.ts`, keep both
   sides, and four hunks in `docs/api/solus.md`, one of which needs a decision rather than a merge.

### Recommended merge order

**251 → 252 → 250.** 252's conflicts are trivial and its two fixes are surgical, two functions in
two files. 250's conflicts are five documentation files that 251 rewrote wholesale; taking it last
means reconciling that prose once against a settled tree rather than twice.

---

## 5. The machine-local and shared split

The new private file is `projects/<projectId>/hardware.json`, schema version 1. Its contract twins
are `packages/contracts/python/solus_contracts/hardware_local_state.py` and
`packages/shared-types/src/hardware-local-state.ts`.

| Field                                | Type                      | Purpose                                 |
| ------------------------------------ | ------------------------- | --------------------------------------- |
| `schemaVersion`                      | literal 1                 | Version gate; a newer file is read-only |
| `accounts`                           | map, max 16               | Keyed by authenticated user UUID        |
| `accounts[].sources`                 | map, max 256              | Keyed by opaque source UUID             |
| `accounts[].sources[].path`          | absolute string, max 4096 | The picker-authorized file              |
| `accounts[].sources[].contentSha256` | 64 lowercase hex          | Digest of the selected bytes            |
| `accounts[].bindings`                | map, max 256              | Keyed by configuration-entry UUID       |
| `accounts[].bindings[].lastSeenPath` | string, max 512, optional | Port hint, never identity               |

Whole document capped at 256 KiB. Every model sets `extra="forbid"`, `frozen` and `strict`.

**What moved out of shared state.** Two things. The transport binding's `last_seen_path` left the
shared configuration document. And calibration or provenance `source` values that were local paths
are now rejected outright by v2 validation, with `is_private_source` refusing them at write time and
the migration rewriting existing ones into an opaque token.

**The split is right.** Calibration values, limits, telemetry channels, firmware and lifecycle stay
shared, so a teammate still sees the facts. Only the two genuinely machine-specific things, a disk
path and a port path, went local. Two engineers on different machines with the robot on different
ports each keep their own hint under their own account key, and neither overwrites the other. A
teammate who needs to know how a part is calibrated reads it from the shared config without ever
seeing where the file sits on someone else's disk.

**The security work is careful.** Verified in `apps/desktop/src/main/hardwareLocalState.ts` and
`hardwareSources.ts`:

- File mode 0600 under a 0700 directory.
- `realpath` and symbolic-link checks on both the directory and the file, blocking a symlink swap.
- Bounded read into a buffer one byte past the cap, so an oversized file is detected rather than
  loaded.
- Atomic write to a randomly named temporary file followed by `rename`.
- Synchronous read-modify-rename, deliberately avoiding event-loop interleaving.
- The account ID is resolved by the server from the auth token. The renderer cannot claim another
  account, and a generation counter invalidates pending replies when the token or project changes.
- Only a sanitized basename leaves MAIN. The parent directory never reaches the renderer or any API
  payload.

**Two gaps.**

1. **MEDIUM — migrated source references can never be relinked.** The migration mints tokens by
   hashing the path together with the subject UUID, while the local store keys sources by a fresh
   random UUID. Nothing maps between the two namespaces. A user whose legacy configuration cited a
   calibration file gets an opaque token that no relink flow can resolve. Calibration _values_ are
   preserved; the ability to re-verify or refresh from the original file is not. A second
   consequence is that two parts calibrated from one file receive unrelated tokens, so shared state
   can no longer express that they share a source.
2. **The feature is dark.** No renderer code calls the three `hardware:sources:*` channels, and no
   server-side reader exists. Both halves are A3.

---

## 6. Pre-merge checklist

Blocking:

- [ ] Fix the owner-key collision in §3.1 and add the promote-on-firmware-bearing-robot test.
- [ ] Add the data migration, its preflight and a fixture dataset, per §3.2.
- [ ] Create the two declared constraints in a migration, after the backfill, per §3.3.
- [ ] Clear the 9 ruff and 9 mypy findings in §3.9. Six of the ruff ones are auto-fixable; leave the
      C901 until §3.1 is settled.

Should fix before handoff:

- [ ] Call `disable_part_bindings` from the robot removal path, or filter deleted subjects in the
      `synchronize_bindings` conflict query, per §3.7.
- [ ] Either wire `configured_endpoint_targets` or delete it, per §3.7.
- [ ] Decide whether `GET /robots/{robot_id}/config` should stop writing and stop locking, per §3.6.
- [ ] Extend the existing router, store, library and bench tests that A1 owned but did not touch.

Then A3 and A4 as the plan specifies.

---

## 7. Not verified

- The Python test suite was **attempted and could not run.** PostgreSQL is not listening on
  127.0.0.1:5432 in this environment, so every database-backed test errors with
  `ConnectionRefusedError` during setup. Start it with `make db-up` before reading any suite result.
  Nothing in this document was reproduced against a live database.
- §3.5's practical impact depends on whether drivers can open a device from its serial number alone.
- Desktop type-checking and the Vitest suites were not run. Python lint and type-checking **were**
  run; see §3.9.
- Conflict predictions came from a three-way textual comparison against the shared ancestor, because
  `git merge-tree` is blocked by the branch-protection hook while the tree is on `main`.

## 8. Unrelated repository note

`.Codex/` is untracked and unignored on `main`, because `.gitignore` covers only `.claude/state/`.
It holds a mirror of the ownership manifests that the plan asked to be duplicated there. Every
subagent stop in this review was truncated by the ownership hook as a result. This branch already
carries the fixing `.gitignore` line, so merging it resolves the problem.
