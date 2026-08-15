# Cowork QA — LANE A: Cross-domain linking & impact (SOLUSDEV-106/107/197/198/113)

Written for Claude Cowork end-to-end testing. Assumes: this file, the running API, and
nothing else. The lane is **backend-only** — the Impact widget (LANE B) still renders
CTR-04 fixtures — so flows are exercised through the HTTP API and the test suite.

## Setup

1. Postgres 16 + pgvector reachable; `uv sync --all-packages` in the repo root.
   ⚠ If the shell exports `VIRTUAL_ENV` pointing at another checkout, run every command
   with `env -u VIRTUAL_ENV` — otherwise you test another worktree's code.
2. API: `env -u VIRTUAL_ENV uv run uvicorn solus_api.main:app` (from `packages/api`),
   `SOLUS_DATABASE_URL` pointing at a scratch DB migrated with `alembic upgrade head`.
3. Auth: any signed JWT the test settings accept (see `packages/api/tests/conftest.py::make_token`).
4. Seed data per flow below (SQL/ORM as noted); the deterministic alternative for every
   flow: `env -u VIRTUAL_ENV uv run pytest packages/api/tests/test_linker.py
   test_engine.py test_consequences.py test_integrations_stack.py -q` must be all-green.

## Flow 1 — Mock linking (LNK-01)

1. Create team + project (POST /api/v1/teams, /projects) → 201s.
2. Seed connector entities matching the committed mock
   (`fingerprint/mock_canonical_parts.json`): for each modality `source_ref`, a live
   `graph_entity` with that exact id, `source_connector`, `external_ref` (kicad→
   electrical, onshape→mechanical, github→code domains).
3. Run `await link_from_mock(session, project_id=...)` (worker/console).
   **Expect**: 16 live `graph_edge` rows, `relation_type="same_as"`, `origin="linking"`;
   NE555's edge confidence 0.55 with `attrs.matched=false`; the ambiguous U12 entity has
   no edges; re-run reports all-zero write counters (idempotent).
4. Edge case: delete one seeded entity → re-link: its edges retract (soft-delete), run
   reports `unresolved` > 0, nothing raises.

## Flow 2 — Real fingerprint linking (LNK-02)

1. Seed two live entities with `modality_hints={"part_number": "LM358"}` (distinct
   `external_ref`s, same project) and one with `{"part_number": "NE555"}`.
2. `await scan_project(session, project_id)` then
   `await link_from_fingerprint(session, project_id=...)`.
   **Expect**: one `same_as` edge between the two LM358 entities (`attrs.matched=true`);
   no edge to the NE555; both LM358 rows share a `canonical_part_id`; the canonical row
   itself has no edges.
3. Edge cases: a datasheet-only entity (`{"datasheet": "lm358.pdf"}`) never links; two
   different parts claiming the same pair at equal confidence → no edge, `ties=1`
   reported; a part with > 64 observations links only the first 64 (`capped_parts=1`).

## Flow 3 — Impact analysis (IMP-01/02)

1. Seed the hero-shaped project: motor (mechanical, focus) ← `driven_by` — driver
   (electrical, `attrs.current_draw_a=3.0`); PSU (electrical, `attrs.current_max_a=1.0`)
   — `powers` → driver; IMU (electrical, `attrs.min_sample_rate_hz=100`) —
   `connected_to` → motor; firmware file (code, `attrs.loop_rate_hz=10`) — `reads_from`
   → IMU.
2. `await compute_impact(session, project_id, focus_id=<motor>, change=[DiffRow(...)],
   provider=checker_provider())`.
   **Expect**: nodes for driver + PSU (critical, power budget), IMU + firmware (warning,
   undersampling); node domains span electrical AND code; every node's
   `distance == len(path)`, path starts at the motor; criticals sort first; result
   validates against `solus_api.contracts.impact.ImpactResult` with `extra="forbid"`.
3. Narration: with no model key configured, every `rationale` ends with
   `[deterministic rationale — narration unavailable]` — impact still returns fully.
   With a key + `build_narrate_fn` wired, rationales are prose and the marker is absent;
   kill the key mid-flow → falls back to marked templates, never errors.
4. Edge cases: focus id from another project → `ValueError` (route: 404); empty graph →
   `nodes=[]`, an honest answer; > 500-entity neighborhood → `truncated=true`.

## Flow 4 — The integrations stack (LNK-08)

Run: `env -u VIRTUAL_ENV uv run pytest packages/api/tests/test_integrations_stack.py -q`
— this IS the joint QA: KiCad + Altium via their real parsers on committed exports,
GitHub/GitLab connector-shaped, fingerprint scan, linking (R1↔R2 and the C-trio
`same_as` edges), the seeded MPU-6050 Nyquist bug caught across code↔electrical, and
`GET /api/v1/projects/{id}/graph` returning the linked result.
Manual variant: replay its steps against the running API; the graph GET must show the
`same_as` edge and the cross-domain reachability.

## Cross-feature interactions

- **Fingerprint invariants hold under linking**: after any flow, no `canonical_part_id`
  exists on a LOW_CONFIDENCE-only observation, and no linker edge was promoted above its
  honest confidence (spot-check `attrs.matched` vs `confidence`).
- **Tenant isolation**: create a second team/project with identical `external_ref`s; run
  every flow on project A; **expect** zero edges or impact nodes referencing project B's
  entity ids, and `GET /projects/{B}/graph` with team A's token → 404.
- **Connector re-sync**: re-run a connector sync after linking; connector-owned edges
  reconcile, linker-owned (`origin="linking"`) edges untouched by the sync, manual edges
  untouched by both.

## Known gaps (expected failures — do not file as new)

- Altium entities never fingerprint/link (empty `modality_hints`) — deferred to LANE G.
- Checkers fire only on seeded/manual attributes until EDA attribute extraction lands.
- No impact HTTP route yet (planned, `docs/api/API-implementation.md` §14); the Impact
  widget renders fixtures.

Checklist: [ ] Flow 1 · [ ] Flow 2 · [ ] Flow 3 · [ ] Flow 4 · [ ] Isolation · [ ] Re-sync
