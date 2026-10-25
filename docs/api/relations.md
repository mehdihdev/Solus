# relations.md — Edges with meaning (SOLUSDEV-320)

**Last updated:** 2026-10-18. Tier-1 route plan (ADR-032). **Authority:** DECISIONS.md ADR-027
(graph conventions; amendment proposed in `docs/qa/COMPLETION_SOLUSDEV-320-graph-workspace.md`),
ADR-001 (graph-centric), CLAUDE.md §7 (ingested text is data). Contract:
`packages/contracts/python/solus_contracts/relations.py` ↔ `packages/shared-types/src/relations.ts`,
pinned by `packages/shared-types/fixtures/relations/_values.json`.

## 1. What an edge says

Every `graph_edge` row answers four questions:

| question | column / key | values |
| --- | --- | --- |
| what kind of connection | `relation_type` | one `RelationType`; its `RelationClass` is `identity`, `structure`, `dependency`, `outcome` or `legacy` |
| which way it runs | `src_id → dst_id`; `attrs.matrix_cell` | the src → dst docstring of the type; one of the nine `MatrixCell`s (`software->electrical`, …) or absent when an endpoint is outside the three worlds |
| what made it | `origin`, `attrs.evidence`, `attrs.created_by` | `EdgeOrigin` ∈ `connector`, `manual`, `inferred`, `fingerprint`, `system`; evidence items `{kind, ref, detail}` with `kind` ∈ `EvidenceKind` |
| how sure | `confidence` | 0..1; an `inferred` edge below **0.8** is a *candidate* |

`domain_pair` is always the two endpoint domains in alphabetical order joined by `<->`
(`normalize_domain_pair`); direction never lives there.

### RelationType

| class | types (src → dst) |
| --- | --- |
| identity | `same_as` observation ↔ observation |
| structure | `contains` parent → child · `part_of` child → parent |
| dependency | `commands` code site → actuator · `reads` code site → sensor · `wires` component ↔ component on a net (`attrs.nets`) · `powers` supply or rail → sink · `drives` bus → device · `mounts` structure → device · `mates_with` part ↔ part (`attrs.mate_type`) · `limits` joint → code constant · `depends_on` manifest owner → package · `requires` hardware config → package · `hosts` machine → robot · `publishes` / `subscribes` ROS node → topic |
| outcome | `measured_by` part → channel · `observed` finding → subject · `fixed_by` error entry → diff or artifact · `verified_by` goal or claim → run or sim result |
| legacy | `connected_to`, `configures`, `binds`, `hardware_connected_to`, `hardware_topology_member`, `hardware_evidence_for`, `presence_prepared_for`, `wiring_proposed_for`, `deployment_for_target`, `cad_visual_for`, `clone_of`, `references`, `reads_from` — written before this vocabulary; readable, never emitted by inference |

## 2. One writer

`packages/api/src/solus_api/graph/edges.py` is the only module that constructs a `GraphEdge`
outside the connector runtime (`test_edge_writer_ratchet.py`). `write_edge` upserts on the live
`(project, src, dst, relation_type, source_id)` key (or an explicit `edge_id` for topology
identities), merges evidence deduped on `(kind, ref)`, keeps `confidence = max(existing, new)`
unless the origin is `manual`, derives `domain_pair` and refuses an unknown relation type.
`confirm_edge` makes a candidate manual (confidence 1.0, `user_confirmed` evidence);
`decline_edge` soft-deletes it with `attrs.declined_by` / `attrs.declined_reason`, and the same
evidence is not re-proposed; `supersede_edge` links an old edge to its replacement.

## 3. Routes

All under `/api/v1/projects/{project_id}`, ProjectCtx (non-member → 404), writes MEMBER (viewer → 403).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/relations` · `/entities/{id}/relations` · `/graph` | unchanged; every relation now carries `confidence`, `origin`, `domain_pair`, `properties` (`evidence`, `matrix_cell`, `created_by`, …) |
| GET | `/edges/candidates?relation_type=&subject=&limit=` | live `inferred` edges with `confidence < 0.8` |
| POST | `/edges/{edge_id}/confirm` | → `origin: manual`, `confidence: 1.0`; emits `graph.changed` |
| POST | `/edges/{edge_id}/decline` `{reason?}` | soft delete; emits `graph.changed` |

Candidates never reach checkers, SOL context or impact: `graph/neighborhood.py:to_graph_context`
drops them. They are visible on the canvas (dashed) and through this route only.

## 4. Inference (`graph/inference/`)

Every module is idempotent, writes `origin = inferred` through `write_edge`, never deletes or
downgrades a `manual` edge, and a rerun with identical inputs leaves ids and `updated_at`
unchanged. Each run returns `InferenceReport(module, created, updated, skipped, candidates)`;
`run_guarded` wraps each module in a SAVEPOINT and logs with the project id, so inference can never
fail a sync, an acceptance or a scene import. Dispatch is by connector **capability**
(`ConnectorRegistry.providers_of`), never by provider name (`test_capability_hygiene.py` covers
this package).

| module | fires from | writes |
| --- | --- | --- |
| `power_nets` | `connectors/runtime.py:_commit_success` when the source has `netlist` | `wires` component ↔ component per shared net (one edge per pair, `attrs.nets`, `attrs.pins`) 1.0, evidence `netlist ref=<net>`; `powers` supply → sink on rail-named nets 0.9. `GND` never powers. Nets with more than `MAX_WIRED_NET_MEMBERS` (32) members write no `wires` (pairwise wiring of a 1000-part ground net hung the sync); `powers` is still written. |
| `firmware_edges` | `TopologyAcceptanceService.confirm` after `ledger.record` (not on replay); repo / local-folder sync with code kinds landed | `commands` code file → part whose `bus_map` address matches a written bus address (0.8 unique, 0.55 when only a host-config literal matches); `reads` code file → part wired to the read pin through `wires.attrs.pins` 0.55; evidence `firmware_symbol ref=<provenance source_ref>` (`file:line`). Rows whose `source_ref` is `source:<uuid>` resolve to no code entity and write nothing. |
| `overlay_edges` | `HostTopologyService.confirm` after `_persist` (not on replay); topology acceptance | `drives` bus → device from `hardware_connected_to` 0.9 (`bus_enumeration ref=<address>`); `hosts` machine → robot 1.0 (`config ref=host:<machine_id>`) when a `machine` node's `canonical_key` matches the confirmed host; sets `robot.attrs.host_machine_id` even when no machine node exists yet. |
| `manifest_edges` + `manifests` | repo / local-folder sync complete | `depends_on` owner → requirement 1.0, evidence `manifest ref=<source_file>`, only from **connector-written** `requires` edges whose requirement carries `attrs.source_file`. `parse_package_json` (dependencies + devDependencies) and `parse_package_xml` (depend, exec_depend, build_depend) are pure; python keeps kind `python_requirement`, npm/ros use `package_requirement` with `attrs.ecosystem`. |
| `config_requires` | end of `hardware/store.py:put_entity_config` | `requires` hardware config → `package_requirement` (`pkg:<ecosystem>:<name>`) 0.8 from `ProtocolDriver.requires_packages` (livebench, imported lazily; ImportError → empty report), evidence `config ref=protocol.driver_id`. |
| `mates` | `_commit_success` when the source has `geometry` | the connector emits `mates_with` 1.0 with `attrs.mate_type`, `attrs.feature_id`, evidence `mate ref=<feature id>`, `matrix_cell mechanical->mechanical` from the **mirrored** assembly definition only (`mates_from_definition`; no live provider call, logged "mates skipped: not mirrored" otherwise); `mounts` structure → device 0.7 for a FASTENED mate joining `behaviour_class structural` to `device`. `mateType` outside `[A-Z_]{1,32}` is skipped. |
| `joint_limits` | `livebench/scene/router.py:finish`; topology acceptance | `limits` bench_scene_model → code file 0.5 candidate, one edge per (model, file) with `attrs.matches = [{joint, constant, line}, …]`. |

`infer_after_sync(session, project_id, *, source_id, registry)` runs inside the sync transaction;
a `run_sync` caller that passes no registry skips inference.

## 5. Error catalogue

| HTTP | `error.code` | Where |
| --- | --- | --- |
| 403 | `forbidden` | confirm/decline as viewer |
| 404 | `not_found` | non-member project; unknown, foreign, deleted or non-candidate edge |
| 409 | `topology_conflict` | an `edge_id` write that collides with an edge another topology marker owns |
| 422 | `validation_error` | unknown relation type, confidence outside 0..1, bad evidence item |
