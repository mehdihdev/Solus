# Completion report — SOLUSDEV-207 (SOLUS-TU-04): tool-knowledge KB schema + storage + confidence model

**Lane:** D (SOLUSDEV-215) · **Branch:** `SOLUSDEV-215-lane-toolkb` · **Date:** 2026-08-08

## What was built

- `packages/api/src/solus_api/toolkb/schema.py` — `ToolKnowledgeEntry` ORM (table
  `tool_knowledge`) mirroring CTR-05 exactly: typed columns only, no JSONB, no customer-owned
  identifier, **no team/project/user column — the absence IS the tenancy boundary**. Storage-side
  columns are all enum/number/timestamp: `status` (candidate|published — staging and the shared
  store are ONE closed shape), `acquired_via` (api_geometry|docs|visual|operator), `confidence`,
  `confirm_count`/`reject_count` (TU-08-ready), `last_verified_at` (TU-07-ready),
  `version_min_key`/`version_max_key`, nullable `embedding vector(1536)` (outside the contract
  shape by design — the contract forbids an embedding field). DB CHECKs: confidence 0..1, counts
  ≥0, `cardinality(menu_path)<=8`, locator all-or-none (`num_nonnulls`, not NULL-algebra) + 0..1
  bounds. Partial-unique identity `(tool, control_id, surface, version_range) WHERE deleted_at IS
NULL`; lookup index `(tool, status, version_min_key)`; HNSW(m=16, ef_construction=64, cosine)
  per ADR-027.
- **Version model**: verbatim `version_range` + derived zero-padded sortable keys
  (`version_key`/`version_keys`) → tool+version queries are pure btree; supports `>= > < <= ~ ^ =`
  and bare tokens with intersection; npm caret semantics incl. major-0 (review-hardened);
  4-digit components (ponytail ceiling noted in code).
- `storage.py` — read side: `query_entries()` serves **published, live** rows only; filters
  (version window, surface, effect, control_id); §1.4 cursor pagination reusing
  `core/pagination.py`.
- `router.py` — `POST/GET /api/v1/toolkb/entries` per `docs/api/toolkb.md` (see SOLUSDEV-209
  report for the guard-hardening this surface carries).
- Migration `f2a9c4d15e07` (down_revision `e3a1c8f27b54`, single head preserved).
- Confidence model: stored initial values api_geometry 0.9 / docs 0.8 / operator 0.7 / visual
  0.5 (provisional — Phase 0 §7.2 asks for human calibration; TU-08 makes it a recompute).

## Governing docs

`docs/contracts/tool-knowledge.md` (CTR-05) · DECISIONS.md ADR-027 (UUIDv7, soft-delete, HNSW),
ADR-003, ADR-032 · `docs/api/toolkb.md` — **tier-1 amendment written with this ticket** (docs/api
had no toolkb plan; flagged per protocol) · CODEOWNERS lane paths. No architecture diagram or
wireflow exists for this lane (flagged in Phase 0; noted, not improvised around).

## Sanctioned @shared touches (recorded in-chat approvals, Phase 0)

- `packages/api/migrations/versions/f2a9c4d15e07_…py` (the migration)
- `packages/api/migrations/env.py` — one metadata import line
- `packages/api/src/solus_api/main.py` — one `include_router` line (+import)
- root `pyproject.toml` — `-p no:launch_ros` added to pytest addopts (pre-existing env failure:
  sourced ROS Jazzy leaked its pytest plugin via PYTHONPATH and crashed collection)
- `packages/api/tests/conftest.py` — two additive fixtures (`unverified_headers`, `make_entry`);
  placed in the ROOT conftest because a `tests/<sub>/conftest.py` shadows the root conftest's
  module name and breaks root-level `from conftest import …` in full runs (bug found + avoided)

## Tests (written first, red→green)

`tests/toolkb/test_schema.py` (unit: version keys incl. npm-caret major-0 + boundary cases; DB:
all CHECKs, partial-unique + soft-delete re-add, fixture round-trips through `to_contract()`
which re-runs the CTR-05 validators on read) · `test_storage.py` (published-only, version-window
boundaries, filters, cursor walk) · `router_test.py` (§ see 209 report). Full `packages/api`
suite: **1640 passed, 0 failed**; mypy clean (133 files).

## Delegated-judgment decisions

- Cursor pagination reuses the existing `(created_at, id)` helper rather than a confidence-order
  cursor (repo-idiom reuse; per-entry confidence still returned).
- Bare/`=` version tokens are an equality window at stated precision (`"2.0"` covers 2.0.x);
  documented in the docstring and pinned by tests.
- `tests/toolkb/router_test.py` uses the `*_test.py` form because a root-level `test_router.py`
  already exists (pytest flat module namespace).

## Open items

Phase 0 §7 questions stand (confidence calibration; TU-05 install-identity sign-off before
TU-05). Environment: KiCad install + Onshape credentials still pending (human) for TU-01.
