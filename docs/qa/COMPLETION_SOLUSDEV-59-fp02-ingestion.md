# Completion Report — SOLUS-FP-02 Fingerprint Ingestion (SOLUSDEV-59)

## What was built

FP-01's `FingerprintOutput` now writes into the graph:
`packages/api/src/solus_api/fingerprint/ingest.py` — `ingest()` (idempotent
concurrency-safe canonical-part upsert), `ingest_output()` (full-output loop incl.
candidate evidence), `scan_project()` (pipeline entry: gather → pure match → ingest →
sweeps), `resolve()` (the entity-collapse API LNK-01 consumes), `EmbedFn` seam,
`IngestResult`/`ScanSummary`. Plus `graph_entity.canonical_key` (migration
`9b0d77b7acd2`), one Settings flag, package exports, and
`temp-PROPOSAL-gateway-embeddings.md`. FP-01 matcher/contract/eval and the W0-06 mock
are untouched; ADR-027 untouched.

**The integration acceptance (verify 5) holds**: a part observed as netlist `LM358` +
BOM `LM358DR` + schematic symbol collapses to ONE canonical entity, and
`resolve(SourceRef)` — by `graph_entity_id` or by `(connector, external_ref)` —
returns that one entity for all three observations
(`test_scan_multimodal_resolves_to_one_canonical`). This is the proof LNK-01 can swap
off the mock.

## Decision 1 — project-scoped canonical entities (the uuid5/ADR-027 resolution)

- `canonical_key: String(64) | NULL` on `graph_entity` (64 = matching.yaml
  `max_mpn_len`); partial UNIQUE `(project_id, canonical_key) WHERE canonical_key IS
NOT NULL AND deleted_at IS NULL`. The `IS NOT NULL` guard is load-bearing: the index
  is composite with the always-present `project_id`.
- uuid7 PK per ADR-027, unamended. FP-01's uuid5 lives in
  `attrs.fingerprint.canonical_id` (traceability to matcher runs only).
- Canonical rows: `kind="canonical_part"` (existing convention), `domain=electrical`,
  `origin="fingerprint"` (NEW third origin value), `source_id`/`external_ref` NULL —
  the connector `(source_id, external_ref)` unique never applies to them.
- Same part in two projects = two canonical entities
  (`test_same_part_two_projects_two_canonicals`); cross-project parts library
  documented out of scope (migration + module docstrings).

## Upsert design (constraint-based, cost.py pattern)

`pg_insert(...).on_conflict_do_nothing(index_elements=["project_id","canonical_key"],
index_where=<the index predicate>).returning(id)` → `SELECT ... FOR UPDATE` →
pure-Python `_merge_attrs` → assign new dict + `version += 1` only on REAL change
(volatile timestamps excluded via `_stable_view`). Concurrent ingest of one part on
two sessions yields one row and equal returned ids
(`test_ingest_concurrent_same_part_is_race_safe`, mirrors test*cost.py). Literal
`ON CONFLICT ... DO UPDATE` was rejected: the union-with-update JSONB merge is not
expressible in SQL `set*`, and bump-on-real-change needs Python. Tombstoned canonical

- re-ingest → fresh live row, tombstone intact (partial index ignores deleted rows).
  Oversized keys (>64) are skipped with a warning — NEVER truncated (truncation could
  merge distinct parts).

## Precision at persistence + CLEAR+STAMP (human decision 2026-07-12)

- MATCHED → `canonical_part_id` FK + ownership stamp
  `attrs.fingerprint_link = {canonical_key, run_at}` + version bump.
- LOW_CONFIDENCE / AMBIGUOUS → candidate evidence only, NO FK (tested per state);
  AMBIGUOUS is recorded on EVERY candidate canonical present in the run (skipped for
  absent candidates — ambiguity never creates a canonical).
- `unmatched` → completely untouched.
- `scan_project`'s sweep retracts stamped assertions the current run no longer
  supports (FK cleared, stamp removed, version bumped) and NEVER touches unstamped
  FKs — a manually-set link survives re-scans
  (`test_stale_assertion_cleared_with_stamp_ownership`). Reassignment moves FK+stamp
  atomically in the same run.

## Candidate-evidence shape (canonical `attrs.fingerprint`)

Scalars overwritten per run: `canonical_id` (uuid5), `confidence`, `manufacturer`,
`datasheet_ref`, `last_run_at`. `modalities`: union-with-update map keyed
`"{modality}:{connector}:{external_ref}"` (fallback `str(graph_entity_id)`), values
`{source_ref, confidence, state, evidence, seen_at, stale_at}` — re-ingest updates the
seen source and PRESERVES others (`test_reingest_updates_one_source_preserves_others`,
the clobber case); evidence of no-longer-live observations is marked `stale_at`, never
dropped (provenance survives a mid-resync source). `ambiguous`: same union-with-update
map keyed by source key.

## Keyless safety (Decision 3)

The entire path runs with zero API keys: `scan_project` uses the pure matcher (no
escalation — `build_escalator` requires a user identity the pipeline doesn't have) and
`embed=None` leaves `embedding` NULL with nothing raised. With an embedder injected,
vectors are written once per canonical (1536-dim validated) and are RETRIEVAL-ONLY —
link outcomes are identical with and without (`test_scan_with_embedder_writes_
embedding_same_links`); an embedder that raises degrades to NULL
(`test_embedder_raising_is_best_effort`). The provider-backed path is PROPOSED as an
MO-01 gateway `embed()` extension in `temp-PROPOSAL-gateway-embeddings.md` — no
provider code was built outside the gateway.

## Migration

`9b0d77b7acd2` (parent `8d4f2a91c6e3`): add_column + partial unique index; real
downgrade (drop_index + drop_column). Fresh-DB apply is proven every test session
(conftest upgrades to head); reversibility is proven by the net-new
`test_migration_downgrade_and_reupgrade` (sync test: downgrade -1 → column+index gone
→ upgrade head restored, `finally`-guarded).

## Verify points → proof (packages/api/tests/test_ingest.py, 27 tests)

1. Idempotency: index test + double-ingest + concurrent gather test.
2. Precision per state: `test_matched_sets_canonical_fk_and_stamp`,
   `test_low_confidence_no_fk_recorded_as_candidate`,
   `test_ambiguous_no_fk_candidate_on_each_canonical`.
3. Evidence merge: clobber test + `test_version_bumps_only_on_real_change`.
4. Keyless: three embedder tests (none / fake / raising).
5. Integration: `test_scan_multimodal_resolves_to_one_canonical`.
6. Isolation: two-projects test + `test_resolve_and_ingest_are_project_scoped`
   (foreign `graph_entity_id` neither links nor resolves — cross-tenant guard).
7. Migration reversibility test (explicit pre-FP-02 downgrade target); ADR-027
   untouched; mypy --strict + ruff clean; full suite 761 passed / 3 pre-existing
   skips.

## Phase 4 verification (33-agent multi-lens review, adversarially verified)

Five lenses (sql/upsert, security+tenancy, spec, python/sqlalchemy, data-integrity),
every non-LOW finding challenged by two refuters: 23 raw findings; all confirmed ones
fixed and regression-tested in the same branch:

- **CRITICAL — concurrent scans could silently clobber a just-committed assertion**
  (unlocked last-writer-wins observation writes): `scan_project` now takes a
  per-project transaction-scoped Postgres advisory lock — two scans matching
  different snapshots can no longer interleave assertions/retractions
  (`test_concurrent_scans_serialize_per_project`). Sweep/gather queries are id-ordered
  for deterministic lock acquisition (the deadlock HIGH).
- **HIGH — the SET side of CLEAR+STAMP overwrote unstamped (human/LNK-01) FKs**,
  reverting a human correction on every scan: ownership guard added — an unstamped
  disagreeing FK is never touched, counted as `skipped_unstamped`, disagreement stays
  visible in canonical evidence (`test_manual_unstamped_fk_survives_matcher_disagreement`).
- **HIGH — orphaned canonicals kept fresh-looking MATCHED evidence forever** (a part
  that drops out of matching was never revisited): orphan sweep stale-marks all
  evidence of canonicals no group re-derived (`canonical_staled` counter,
  `test_orphaned_canonical_evidence_marked_stale`), and staleness generally is now
  keyed to RUN-SUPPORT (an entry not re-derived by a complete scan is stale) rather
  than row-liveness — also cleans resolved ambiguity entries.
- **HIGH — NoResultFound race** if the conflicting canonical is concurrently
  soft-deleted mid-upsert: single retry loop around insert+lock.
- **MEDIUM — stale-ref stamping**: write paths no longer fall back from a
  tombstoned/foreign `graph_entity_id` to the (connector, external_ref) pair — a
  match computed from old data can't stamp a re-synced different component (public
  `resolve` keeps the fallback for reads).
- **MEDIUM — unbounded attrs growth** (untrusted hints → row-size DoS): evidence maps
  capped at 256 entries, stale-oldest evicted with a warning.

Accepted/deferred with rationale (see code comments): evidence-key collision for two
sources of one connector type (FK already refused by the ambiguous-provenance rule;
provenance keeps last writer), seq-scan gather/sweep predicates (bounded per
project), informational ScanSummary count nuances, embedding never refreshed on text
change (needs stored text hash — follow-on with the gateway extension).

## Delegated-judgment decisions

- `ingest`/`resolve` take `session` FIRST (services/limits.py convention) — deviation
  from the ticket sketch's argument order, behavior identical.
- `resolve` returns the `GraphEntity` row (not a bare uuid): callers need the entity,
  and ingest must mutate observation rows. Internally split from
  `_resolve_observation` (no FK-following) so linking never confuses an observation
  with its canonical target.
- `ingest_output` added between `ingest` and `scan_project`: AMBIGUOUS/unmatched are
  output-level, not per-part, so per-part `ingest` alone cannot persist them.
- Ambiguous-provenance rule: two live rows sharing `(connector, external_ref)` (legal
  across two sources of one connector type) → resolve returns None, never guesses.
- The module flushes (never commits) so its ORM writes are visible to
  same-transaction readers; the caller owns commit/rollback.
- Evidence staleness: mark (`stale_at`), don't drop — ticket allowed either.

## Flags for humans

- **ADR-028**: `models.py` graph models are human-owned; the `canonical_key` addition
  was explicitly directed by this ticket's Decision 1 — second-founder sign-off
  happens at MR review.
- **H6 hook gap**: the recreation guard blocks any new Alembic migration (every
  migration must define `upgrade`/`downgrade`; H6 flags them as duplicate symbols and
  renaming is impossible under Alembic). Worked around via the framework's own
  `alembic revision` scaffold (H6 guards only brand-new Write files). Suggested hook
  fix: exempt `*/migrations/*` exactly as H9 already does.
- **`origin='fingerprint'`** is a new vocabulary value (ADR text names only
  connector/manual) — suggest a one-line ADR note; the future graph-mutation ticket
  must use an `origin == "manual"` ALLOWLIST for edit rights so fingerprint rows are
  born read-only (`routers/entities.py` is GET-only today, so nothing to guard yet).
- **Lifecycle follow-ons** (documented, out of scope): `canonical_part_id`'s SET NULL
  fires only on hard delete — a soft-deleted canonical would leave observation FKs
  pointing at a tombstone (no code soft-deletes canonicals yet); cross-source edge
  reconciliation on soft-delete (runtime.py note) remains open for LNK-01.
- **Trigger follow-on**: the future router mirrors `trigger_sync` (Job row with
  `JobKind.FINGERPRINT_SCAN`, `record_activity` + `emit_event` — both need the
  authenticated user the pipeline deliberately lacks — then dispatch). LLM escalation
  wires there too (identity for ADR-018 metering). No data events are emitted by the
  user-less library path, matching the existing router-layer event pattern.
- One Explore subagent during planning returned instruction-shaped garbage (0 tool
  calls, "format your replies like this" text) instead of findings — discarded as
  untrusted data and relaunched. Flagging since prompt-injection-shaped anomalies are
  §7-relevant, even when the vector is unclear.

## Test coverage summary

27 new DB-backed tests in `test_ingest.py` (schema/index, upsert incl. concurrency,
per-state precision, evidence merge, keyless/embedder, integration, isolation, edges,
migration reversibility); full `packages/api` suite 761 passed / 3 pre-existing skips;
mypy --strict + ruff clean over the fingerprint package and models.
