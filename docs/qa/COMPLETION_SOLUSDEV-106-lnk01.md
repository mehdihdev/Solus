# Completion — SOLUSDEV-106 (SOLUS-LNK-01): Cross-domain linking against the W0-06 mock

Branch: `SOLUSDEV-63-solus-graph` · LANE A · 2026-08-08

## What was built

`packages/api/src/solus_api/linking/` (CODEOWNERS `@lane-graph`; the ticket's
`backend/app/linking/linker.py` path was stale boilerplate):

- `linker.py` — `link(session, output, *, project_id) -> LinkResult`: for each
  `CanonicalPart`, resolves observation `SourceRef`s to live same-project entities and
  reconciles pairwise `same_as` edges (`origin="linking"`, `source_id` NULL) with
  `domain_pair` + honest confidence. `link_from_mock(session, *, project_id)` is the
  LNK-01 data source — the exact boundary LNK-02 swaps.
- Confidence = `min(part.confidence, obs_a.confidence, obs_b.confidence)`; a pair
  supported multiple ways keeps its best support. Edges whose winning support includes a
  non-MATCHED observation carry `attrs["matched"] = False` and the true low confidence —
  never promoted (FP precision posture preserved).
- Ambiguous observations: counted, never edged. Unresolvable/ambiguous-provenance refs:
  counted, never guessed (two live entities sharing `(connector, external_ref)` refuse
  resolution, mirroring fingerprint `resolve()` semantics).
- Retraction: linker-owned live edges absent from the current output are soft-deleted;
  connector-owned and manual edges are never touched.
- Idempotency: per-project advisory lock (same key as fingerprint ingest, so linker and
  scanner serialize) + select-then-upsert; re-link of unchanged output is a no-op
  (`LinkResult()` all-zeros except the restated ambiguous count).

## Governing docs consulted

CLAUDE.md §§5–7 · DECISIONS.md ADR-001/012/027 (Decisions A/C) · `docs/contracts/fingerprint-output.md` (W0-06) · CODEOWNERS (SOLUSDEV-222/CTR-07) · Jira SOLUSDEV-106 + Phase 0 re-scope comment.

## Tests (written first, red → green)

`packages/api/tests/test_linker.py` — 15 tests: cross-domain edge shape (relation,
origin, domain_pair, confidence, attrs), direction normalization (src < dst by id),
multi-instance pairwise linking, honest low-confidence edges + flag counters,
best-support dedup, idempotent re-link, in-place confidence update, retraction scoped to
linker-owned edges (manual edge survives), unresolved-ref tolerance, ambiguity refusal
(both observation- and provenance-level), cross-project isolation (foreign
`graph_entity_id` never resolves), and the committed-mock end-to-end (16 edges across
electrical/mechanical/code, NE555 at 0.55 unpromoted, U12 un-edged, idempotent re-run).
Full `packages/api` suite green: 1683 passed, 3 skipped.

## Decisions under delegated judgment

- **Pairwise topology** between resolved observations (no canonical hub node exists in
  the mock scenario — FP-02 creates those; LNK-02 revisits against real output).
- **Weakest-link confidence capped by part belief**; best support wins per pair.
- **Resolver duplication**: `_resolve` intentionally re-implements fingerprint ingest's
  private resolver semantics (~30 lines) rather than importing it — the mock-and-swap
  seam forbids FP-01/02 imports; linking meets the fingerprint only at the contract.
- **Reappearing pairs get a fresh row** (tombstone kept as history), mirroring connector
  reconciliation.

## Flags for the human

1. **No DB idempotency backstop for linker edges**: `uq_graph_edge_source_edge` includes
   the NULL `source_id` and Postgres treats NULLs as distinct. The advisory lock is the
   guarantee; a LANE 0 ticket should add a partial unique index
   `(project_id, src_id, dst_id, relation_type) WHERE source_id IS NULL AND deleted_at IS NULL`
   (`models.py`/migrations are `@shared` — outside lane ownership).
2. The contract's promised `SAME_AS` edge now exists via this module; the FP-02
   `canonical_part_id` FK and these edges are complementary (FK = collapse onto a
   canonical row; edges = observation-to-observation identity mesh).
3. Phase-4 review passes (code review + security) run once over the combined LNK-01+02
   linking diff after LNK-02, since both tickets shape one module.
