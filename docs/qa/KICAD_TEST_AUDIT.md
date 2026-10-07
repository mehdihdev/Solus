# KiCad integration — test audit (SOLUSDEV-312)

Scope: acceptance criteria 3, 4, 9 and 10 of the KiCad integration. For each: the tests
that already existed, the gaps found, and the tests added to close them. Paths are under
`packages/api/tests/` unless stated. All API tests were run against a private database
(`SOLUS_TEST_DATABASE_URL=…/solus_test_kicad_b`).

New files: `test_kicad_audit_file_pick_ingest.py`, `test_kicad_audit_hostile_input.py`,
`test_kicad_audit_isolation.py`, `test_kicad_audit_model_context.py`,
`test_kicad_audit_cross_feature.py`, helpers in `fixtures/kicad_audit.py`, and
`apps/desktop/src/renderer/src/features/onboarding/kicadFilesFixtures.test.ts`.

## Criterion 3 — file-pick ingestion

| Behaviour | Existing tests | Gap | Closed by |
|---|---|---|---|
| XML netlist → components/nets/pins | `test_kicad_ingest_e2e::test_real_fixture_lands_expected_component_and_net_entities` (9-part fixture, SDA/SCL pins) | pin-level parity of the small sample across all shapes | `file_pick_ingest::test_every_input_shape_lands_the_same_pin_level_connectivity[xml_netlist]` |
| Default S-expression `.net` | `…::test_sexpr_export_lands_the_same_graph_shape_as_the_xml_twin`, `test_kicad_netlist_sexpr` (parity) | edge-level pins compared only for one edge | `…[sexpr_netlist]` (all six edges + pins) |
| `.kicad_pcb` alone | `…::test_board_only_source_lands_board_only_parts_without_edges` | none material | `…[board_alone]` (adds identical connectivity for U1/R1/C1; H1/FID1 edgeless) |
| Netlist + board together | connector-level only: `test_kicad_connector::test_both_inputs_merge_with_the_netlist_authoritative`, `test_kicad_reconcile` | **no HTTP/graph-level test**; mismatch SyncErrors never seen through `/syncs` | `…[netlist_plus_board]`, `test_netlist_plus_board_is_netlist_authoritative_with_board_layer_and_mismatches`, `test_a_board_only_change_resyncs_and_surfaces_a_new_mismatch_without_touching_the_graph` |
| Re-sync diffs | `test_resync_identical_content_is_idempotent` (identical content only) | **changed content never diffed** (create/update/delete counts, soft-delete, stable ids) | `test_resync_with_changed_netlist_creates_updates_and_deletes_exactly_the_diff` |
| `.kicad_sch` / `.kicad_pro` refused server-side with guidance | connector/parser level: `test_kicad_netlist::test_raw_schematic_…`, `test_project_file_…`, `test_kicad_formats`, `test_kicad_connector::test_schematic_in_export_is_refused…` | **not proven through the route**: failed sync, `{code,message}` on the source, nothing half-ingested, prior graph kept, recovery | `test_misrouted_or_design_files_fail_the_sync_with_guidance_and_ingest_nothing` (6 cases), `test_missing_inputs_name_both_config_keys`, `test_a_refused_resync_keeps_the_previous_good_graph_and_recovers_on_a_valid_file` |
| Client: classification/routing/guidance | `apps/desktop/…/onboarding/kicadFiles.test.ts` (32), `edaConnect.test.ts` (empty/oversize/per-file bound, error surfacing), `useConnectWizard.test.ts` (read failure) | classifier only exercised on synthetic one-liners, never on the committed real files | `kicadFilesFixtures.test.ts` (14: real XML, hostile, 1001-part, `kicad-cli` `.net`, board, schematic, project, BOM, renamed files) |

## Criterion 4 — hostile input (Flows 6 / 6a)

Existing: parser-level guards in `test_kicad_sexpr` (depth 64, node cap, control chars, pruning,
8 MiB atom flood under a memory ceiling), `test_kicad_netlist` (DTD/entity), `test_kicad_netlist_sexpr`,
`test_kicad_connector::test_oversized_board_is_refused`, `test_sources` (422 at the boundary for an
over-cap `board`), `test_kicad_ingest_e2e` (1001-part, hostile fixture ingests inertly).

Gap: the QA plan's claim is end-to-end ("nothing crashes"); no test drove hostile bytes through
connect → sync → source status and then proved the API and the same source recover.

Closed by `test_kicad_audit_hostile_input.py`:
- 16 refused-cleanly cases (`test_hostile_input_fails_the_sync_cleanly_and_the_api_recovers`): 200k-deep
  nesting (open/balanced/board), NUL and C0 in S-expr/board/XML, `&#0;`, billion-laughs, external
  entity (`file:///etc/passwd`), parameter-entity SSRF, bare `<!ENTITY`, unterminated, truncated XML,
  wrong root, 250k-component node bomb. Each asserts: terminal `failed` (never stuck RUNNING/SYNCING),
  `export_invalid`, bounded message, nothing echoed or ingested, then the SAME source syncs a valid file.
- Accepted-but-bounded: 200k nested XML under `<export>` (scoped out), 7 MiB repeated component
  (bounded time, one entity), 100 KB net name (record stays small), 70 KB mismatching board `Value`
  (message clipped, record bounded), components smuggled in `zone`/`segment`/`via` (never entities),
  `<!DOCTYPE` literal inside an S-expression value (not a false-positive refusal).
- Size boundary: over-cap `export` and `board` → 422 with nothing stored and payload not reflected;
  multibyte export measured in bytes, not characters.
- 1001-part fixture: clean sync (zero errors, bounded time) and a no-op re-sync.

## Criterion 9 — isolation and security

Existing: `test_sources` (list/get/patch of a kicad source → 404 for a stranger; config never echoed),
`test_artifacts`/`test_artifact_upload` (generic cross-team artifact read, one with `kicad.export_project`),
`test_context::test_tenant_scope_reaches_every_feed`, `test_graph_read_scope`.

Gaps: no KiCad-specific isolation across the other source routes (delete, sync, syncs, sync detail,
selectable, documents), entity routes (list/get/relations/patch/delete/graph/relations), jobs, and the
reasoning layer; no test of the cross-PROJECT id-guessing case; the injection fixture was never carried
through the real context assembler.

Closed by `test_kicad_audit_isolation.py` (47 tests): a 22-route table (every route that can touch KiCad
data) driven by team B against team A's project (403/404, no A content in the body) and — for the 11
id-bearing routes — against B's OWN project with A's ids; job ids; list routes in B's project; A's
state fingerprint unchanged after every attempt; 401 unauthenticated on all 22; forged token;
`load_neighborhood`, `DbSolSystems.get_graph_context`, `scan_project` and BOM `load_inputs` for B's
project never see A's entities (and ARE populated for A, so the checks have teeth).

Closed by `test_kicad_audit_model_context.py` (6): `solus_sample_hostile.net.xml` synced via HTTP; the
plants are proven present in the graph; `build_context(...).fenced(nonce)` shows every plant only on a
fenced single-line JSON body, `<` escaped (`</export>` never reappears), nothing outside fences; context
spine identical to the benign fixture; system prompt carries no plant; tool set identical for hostile and
benign projects and `kicad.set_symbol_property` is not offered/invocable; real `query_graph` and
`run_checkers` results pass `contain_result` as one escaped ASCII line.

## Criterion 10 — cross-feature

Existing: `test_integrations_stack` (fingerprint + linking + impact via `apply_sync_result`),
`test_kicad_connector::test_sync_carries_the_fingerprint_channels`, `test_sources`, `test_connect_integration`.

Gaps: fingerprint/linking never exercised from the HTTP sync; no BOM-from-KiCad test at all; Sources
status across failure/recovery; no test of any data-collection event for KiCad actions; a linker bug
(below).

Closed by `test_kicad_audit_cross_feature.py` (12):
- Fingerprint: HTTP sync → `scan_project` → `link_from_fingerprint` gives 6 canonical parts and the
  R1/R2 and C1/C2 `same_as` links with no false merges; a CAD part carrying the MCU MPN links to U1; a
  board-only source feeds MPN hints; a re-sync that drops a part retracts its link (**found the bug below**).
- BOM: rows aggregate KiCad parts by MPN with quantities (every component exactly once); a CAD twin is
  two rows until linked, then one cross-domain row.
- Sources / Connected accounts: status, `entity_count`, `last_error` `{code,message}`, config never echoed
  through connected → error → healed; catalog lists kicad with `auth_kind none` and `export`/`board`;
  disconnect removes the graph and the activity feed records connected / sync_started / disconnected.
- Events (ADR-011): a consented user gets exactly `source.connected {type}` and `source.sync_started
  {source_id}` scoped to user/team/project with no design content in the payload; no consent, no rows.

## Real bug found and fixed

`linking/linker.py::link` read its own live `same_as` edges through `GraphReadScope.edge_predicate()`,
which hides edges with a soft-deleted endpoint. After a KiCad re-sync removed a part, the linker edge to
it was never retracted and stayed live (dangling). Fix: select linker-owned edges by project id.
Regression: `test_a_resync_that_drops_a_part_retracts_its_fingerprint_link`.

## Open gaps (not fixed — need a human decision)

1. **No data event when a sync finishes.** ADR-011 names "every sync", but `runtime._commit_success` /
   `_record_failure` emit nothing; only `source.sync_started` (and `source.connected`) exist, and there
   is no event for disconnect or source PATCH (activity feed covers disconnect). Pinned as a strict xfail:
   `test_a_finished_kicad_sync_emits_an_outcome_event` — it flips when an outcome event lands. Choosing
   event names/payloads is a schema decision. `packages/contracts` has no server-event schema file to
   check names against.
2. **BOM HTTP route not covered for KiCad data.** `/widgets/bom/rows` needs the first-party `bom`
   bundle provisioned and installed (`require_bundle`); a seeded fixture manifest returns "No such
   bundle". Coverage is at the layer the route calls (`load_inputs(...).rows()`), which is its whole data path.
3. **Stale QA doc.** `COWORK_QA_kicad-natural-ingestion.md` Flow 8 says the catalog lists kicad with
   `config_fields: ["export","board"]`; the connector also exposes `project_path`. The new test asserts
   the two design inputs are present rather than the exact list.
