# relations.md — Edges with meaning (SOLUSDEV-320)

**Last updated:** 2026-10-28. Tier-1 route plan (ADR-032). **Authority:** DECISIONS.md ADR-027
(graph conventions; amendment proposed in `docs/qa/COMPLETION_SOLUSDEV-320-graph-workspace.md`),
ADR-001 (graph-centric), CLAUDE.md §7 (ingested text is data). Contract:
`packages/contracts/python/solus_contracts/relations.py` ↔ `packages/shared-types/src/relations.ts`,
pinned by `packages/shared-types/fixtures/relations/_values.json`.

## 1. What an edge says

Every `graph_edge` row answers four questions:

| question                | column / key                                   | values                                                                                                                                                |
| ----------------------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| what kind of connection | `relation_type`                                | one `RelationType`; its `RelationClass` is `identity`, `structure`, `dependency`, `outcome` or `legacy`                                               |
| which way it runs       | `src_id → dst_id`; `attrs.matrix_cell`         | the src → dst docstring of the type; one of the nine `MatrixCell`s (`software->electrical`, …) or absent when an endpoint is outside the three worlds |
| what made it            | `origin`, `attrs.evidence`, `attrs.created_by` | `EdgeOrigin` ∈ `connector`, `manual`, `inferred`, `fingerprint`, `system`; evidence items `{kind, ref, detail}` with `kind` ∈ `EvidenceKind`          |
| how sure                | `confidence`                                   | 0..1; an `inferred` edge below **0.8** is a _candidate_                                                                                               |

`domain_pair` is always the two endpoint domains in alphabetical order joined by `<->`
(`normalize_domain_pair`); direction never lives there.

### RelationType

| class      | types (src → dst)                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| identity   | `same_as` observation ↔ observation                                                                                                                                                                                                                                                                                                                                                                                                                 |
| structure  | `contains` parent → child · `part_of` child → parent                                                                                                                                                                                                                                                                                                                                                                                                 |
| dependency | `commands` code site → actuator · `reads` code site → sensor · `wires` component ↔ component on a net (`attrs.nets`) · `powers` supply or rail → sink · `drives` bus → device · `mounts` structure → device · `mates_with` part ↔ part (`attrs.mate_type`) · `limits` joint → code constant · `depends_on` manifest owner → package · `requires` hardware config → package · `hosts` machine → robot · `publishes` / `subscribes` ROS node → topic |
| outcome    | `measured_by` part → channel · `observed` finding → subject · `fixed_by` error entry → diff or artifact · `verified_by` goal or claim → run or sim result                                                                                                                                                                                                                                                                                            |
| legacy     | `connected_to`, `configures`, `binds`, `hardware_connected_to`, `hardware_topology_member`, `hardware_evidence_for`, `presence_prepared_for`, `wiring_proposed_for`, `deployment_for_target`, `cad_visual_for`, `clone_of`, `references`, `reads_from` — written before this vocabulary; readable, never emitted by inference                                                                                                                        |

## 2. One writer

`packages/api/src/solus_api/graph/edges.py` is the only module that constructs a `GraphEdge`
outside the connector runtime (`test_edge_writer_ratchet.py`). `write_edge` upserts on the live
`(project, src, dst, relation_type, source_id)` key (or an explicit `edge_id` for topology
identities), merges evidence deduped on `(kind, ref)`, keeps `confidence = max(existing, new)`
unless the origin is `manual`, derives `domain_pair` and refuses an unknown relation type.
`confirm_edge` makes a candidate manual (confidence 1.0, `user_confirmed` evidence);
`decline_edge` soft-deletes it with `attrs.declined_by` / `attrs.declined_reason`, and the same
evidence is not re-proposed; `supersede_edge` links an old edge to its replacement.

`annotate_edge(session, project_id, edge_id, *, checker_results=None, confirmed_by=None)` is the
one writer of `attrs.checker_results` (SOLUSDEV-321 P3), and the one way evidence from outside the
graph raises an edge that already stands (P6, R131).

- It validates each item as a `CheckerResult`.
- Its callers hold `lock_project`. Under it, it re-reads the live edge of the project fresh,
  under a row lock (foreign, deleted or unknown → 404 `not_found`). Whatever another writer
  committed on the row since the caller read it (a sync's nets, an acceptance's commanded fact) is
  therefore kept, never written back from a stale copy.
- It never waits for that lock (`SKIP LOCKED`). A row another transaction holds returns `None`
  and nothing is written. A sync locks edge rows before the project lock, so waiting while
  holding the project lock could deadlock.
- It reassigns `attrs` with the keys it was given and flushes. Given `checker_results` alone,
  nets, pins, evidence, origin, confidence and `managed_by` stay as the writer that made the edge
  left them.
- `confirmed_by: EdgeEvidence` (a live `ros2` listing, `kind=bus_enumeration`) merges that item
  into `attrs.evidence` (deduped on `(kind, ref)`) and raises `confidence` to 1.0; `origin` stays,
  since a listing is not a person. It never creates an edge.

A matrix run never uses `write_edge(edge_id=…)` for this — it
replaces attrs and evidence, revives tombstones and 409s on `managed_by`. Each item is
`{rule_id, status, severity, message, evidence, at}`: `status` ∈ `pass`, `fail`, `inconclusive`,
`unknown_input` (only `fail` is a problem; `unknown_input` names a fact the project does not
state, under `evidence.missing` when a rule's store-wide need is unmet), `severity` a checker
`Severity`, `at` ISO-8601 in UTC.

The writer of those items is the matrix run (`checkers/matrix_runner.py:run_matrix`, P3-T3), after
every graph change (`docs/api/findings.md` §5). A result names its edge by
`(src_id, dst_id, relation_type)`, so every live row with that triple gets the list, whatever its
`source_id`: a result describes the relation, not one connector's row. One write per edge carries
every result the run's rules gave it, and only an edge whose verdicts moved is written: an item
that says what the edge's old item said keeps the old one, its `at` included. Items of rules the
run did not run (a run over some cells) are kept, and a rule's item on an edge it no longer judges
is removed. A run never appends a duplicate. The facts the rules read off an edge:

- `commands.attrs.commanded = {min, max, unit, min_ref, max_ref}`: the literal goal range of the
  reviewed goal calls to that part, `unit` `deg` when the call names degrees, else `raw`, and
  `min_ref` / `max_ref` the `file:line` of each end. It is `null` when no literal goal stands
  (goals in two units state none), and every write of the edge carries it.
- `limits.attrs.matches[].value` / `.unit`: the number a motor constant states and its unit from
  the constant's name (`deg`, `rad` or `raw`). A rate (an angular one too: `omega`, `rad_per_s`,
  `rad_s`, `rpm`, each only as a whole token of the name, so plural `RADS` and the `rpM` of
  `warpMode` are positions), an effort or a pin constant carries none. A constant names a joint only when the
  joint's name in it is not followed by a digit (`JOINT11_MAX` names no `joint1`).

Entity attrs Solus writes on a connector's own rows — `expected`, `motifs`, `motif_labels`,
`sim_asked` (`connectors/runtime.py:SOLUS_OWNED_ATTR_KEYS`) — are carried over by that
connector's re-sync when it does not emit the key itself; a key it emits wins.

## 3. Routes

All under `/api/v1/projects/{project_id}`, ProjectCtx (non-member → 404), writes MEMBER (viewer → 403).

| Method | Path                                                 | Purpose                                                                                                                                |
| ------ | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/relations` · `/entities/{id}/relations` · `/graph` | unchanged; every relation now carries `confidence`, `origin`, `domain_pair`, `properties` (`evidence`, `matrix_cell`, `created_by`, …) |
| GET    | `/edges/candidates?relation_type=&subject=&limit=`   | live `inferred` edges with `confidence < 0.8`                                                                                          |
| POST   | `/edges/{edge_id}/confirm`                           | → `origin: manual`, `confidence: 1.0`; emits `graph.changed`                                                                           |
| POST   | `/edges/{edge_id}/decline` `{reason?}`               | soft delete; emits `graph.changed`                                                                                                     |

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

| module                         | fires from                                                                                                                 | writes                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `power_nets`                   | `connectors/runtime.py:_commit_success` when the source has `netlist`                                                      | `wires` component ↔ component per shared net (one edge per pair, `attrs.nets`, `attrs.pins`) 1.0, evidence `netlist ref=<net>`; `powers` supply → sink on rail-named nets 0.9. `GND` never powers. Nets with more than `MAX_WIRED_NET_MEMBERS` (32) members write no `wires` (pairwise wiring of a 1000-part ground net hung the sync); `powers` is still written.                                                                                            |
| `firmware_edges`               | `TopologyAcceptanceService.confirm` after `ledger.record` (not on replay); repo / local-folder sync with code kinds landed | `commands` code file → part whose `bus_map` address matches a written bus address (0.8 unique, 0.55 when only a host-config literal matches); `reads` code file → part wired to the read pin through `wires.attrs.pins` 0.55; evidence `firmware_symbol ref=<provenance source_ref>` (`file:line`); `commands.attrs.commanded` from the literal goal calls (§2). Rows whose `source_ref` is `source:<uuid>` resolve to no code entity and write nothing.       |
| `overlay_edges`                | `HostTopologyService.confirm` after `_persist` (not on replay); topology acceptance                                        | `drives` bus → device from `hardware_connected_to` 0.9 (`bus_enumeration ref=<address>`); `hosts` machine → robot 1.0 (`config ref=host:<machine_id>`) when a `machine` node's `canonical_key` matches the confirmed host; sets `robot.attrs.host_machine_id` even when no machine node exists yet.                                                                                                                                                            |
| `manifest_edges` + `manifests` | repo / local-folder sync complete                                                                                          | `depends_on` owner → requirement 1.0, evidence `manifest ref=<source_file>`, only from **connector-written** `requires` edges whose requirement carries `attrs.source_file`. `parse_package_json` (dependencies + devDependencies) and `parse_package_xml` (depend, exec_depend, build_depend) are pure; python keeps kind `python_requirement`, npm/ros use `package_requirement` with `attrs.ecosystem`.                                                     |
| `config_requires`              | end of `hardware/store.py:put_entity_config`                                                                               | `requires` hardware config → `package_requirement` (`pkg:<ecosystem>:<name>`) 0.8 from `ProtocolDriver.requires_packages` (livebench, imported lazily; ImportError → empty report), evidence `config ref=protocol.driver_id`.                                                                                                                                                                                                                                  |
| `mates`                        | `_commit_success` when the source has `geometry`                                                                           | the connector emits `mates_with` 1.0 with `attrs.mate_type`, `attrs.feature_id`, evidence `mate ref=<feature id>`, `matrix_cell mechanical->mechanical` from the **mirrored** assembly definition only (`mates_from_definition`; no live provider call, logged "mates skipped: not mirrored" otherwise); `mounts` structure → device 0.7 for a FASTENED mate joining `behaviour_class structural` to `device`. `mateType` outside `[A-Z_]{1,32}` is skipped.   |
| `joint_limits`                 | `livebench/scene/router.py:finish`; topology acceptance                                                                    | `limits` bench_scene_model → code file 0.5 candidate, one edge per (model, file) with `attrs.matches = [{joint, constant, line, value?, unit?}, …]` (§2).                                                                                                                                                                                                                                                                                                      |
| `ros_edges` (SOLUSDEV-321 P6)  | repo / local-folder sync with code kinds or `ros_node` / `ros_topic` landed (STRUCTURE)                                    | `publishes` / `subscribes` `ros_node` → the SAME source's `ros_topic` named in the node's `attrs.publishes` / `attrs.subscribes` 0.9, evidence `config ref=<attrs.launched_at>` (`launch file:line`) with `detail = "declared at <module>:<line>"`. Its own inferred edges that a re-sync no longer declares are retired. A live listing (`code.ros2_nodes` / `code.ros2_topics`) only RAISES an existing edge to 1.0 through `annotate_edge(confirmed_by=…)`. |

`infer_after_sync(session, project_id, *, source_id, registry)` runs inside the sync transaction;
a `run_sync` caller that passes no registry skips inference.

## 5. Error catalogue

| HTTP | `error.code`        | Where                                                                      |
| ---- | ------------------- | -------------------------------------------------------------------------- |
| 403  | `forbidden`         | confirm/decline as viewer                                                  |
| 404  | `not_found`         | non-member project; unknown, foreign, deleted or non-candidate edge        |
| 409  | `topology_conflict` | an `edge_id` write that collides with an edge another topology marker owns |
| 422  | `validation_error`  | unknown relation type, confidence outside 0..1, bad evidence item          |
