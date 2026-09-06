# COWORK QA — STORE ST2: widgets in the graph (SOLUSDEV-246)

An installed extension registers a graph node that is a peer of Live Bench under a per-project
workspace root; uninstall removes the node and every edge. Written for a tester with the running
application and this file only. Setup is the same as `COWORK_QA_store-st1-widget-bundle.md` §0
(API + ARQ worker + Postgres/Redis; two accounts, STAFF and COMMUNITY; a project `P`), plus:

- The dev database must be migrated to head (`c4d5e6f7a8b9`): `cd packages/api && uv run alembic upgrade head`.
- A BOM bundle to install: zip `docs/extensions/getting-started.md`'s hello-widget with `id = "bom"`,
  `name = "BOM"`, publisher `Ada Lovelace`, or reuse the test fixture (`fixtures.extensions.full_files`).
  Publish it as COMMUNITY and wait for `approved` (poll the review route **as the publisher**).

Shorthands: `H` = STAFF's bearer header; `GRAPH` = `GET /api/v1/projects/P/widgets/graph`.

## 1. The layer exists before any install

| #   | Step                                                | Expected                                                                                                                                                                                                             | Pass |
| --- | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 1.1 | `GRAPH` on a fresh project.                         | `200`; `root` is `type: solus:workspace`, `domain: workspace`, `origin: system`, name `Workspace`; `live_bench` is `solus:live_bench` / `Live Bench`; `widgets: []`; exactly one edge `root -contains-> live_bench`. | ☐    |
| 1.2 | Repeat 1.1.                                         | Same ids — singletons, no duplicates.                                                                                                                                                                                | ☐    |
| 1.3 | `GET /api/v1/projects/P/entities?domain=workspace`. | The two nodes are listed like any entity (`type`, `domain: workspace`, `origin: system`). No other domain filter returns them.                                                                                       | ☐    |

## 2. Install BOM → a BOM node appears

| #   | Step                                                                                                                | Expected                                                                                                                                                                                                                                                                        | Pass |
| --- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 2.1 | `PUT /api/v1/projects/P/extensions/bom` with grants matching the manifest (the fixture declares `graph.read` only). | `201`.                                                                                                                                                                                                                                                                          | ☐    |
| 2.2 | `GRAPH`.                                                                                                            | `widgets` has one entry: name `BOM`, `type: solus:widget`, `domain: workspace`, `origin: system`, `properties` `{ slug: "bom", version: "1.2.0", enabled: true, publisher: "Ada Lovelace", views: [...] }`; two edges, both from the root: to `live_bench` and to the BOM node. | ☐    |
| 2.3 | Repeat 1.3.                                                                                                         | Three rows: `solus:workspace`, `solus:live_bench`, `solus:widget` (`BOM`).                                                                                                                                                                                                      | ☐    |
| 2.4 | Desktop → Context Model screen for `P`.                                                                             | The list shows `Workspace`, `Live Bench` and `BOM` with `solus:… · workspace` under each; selecting one drives focus like any entity; nothing crashes on the new domain.                                                                                                        | ☐    |
| 2.5 | Install a second bundle (e.g. the ST1 fixture as STAFF).                                                            | `GRAPH.widgets` has two entries; each has exactly one `contains` edge from the root.                                                                                                                                                                                            | ☐    |
| 2.6 | The `extension.install` data event (consented user).                                                                | Payload carries `graph_node_id` equal to the BOM node's id.                                                                                                                                                                                                                     | ☐    |

## 3. The node follows the install row

| #   | Step                                                                                          | Expected                                                                                                                           | Pass |
| --- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 3.1 | `PATCH …/extensions/bom {"enabled": false}`, then `GRAPH`.                                    | BOM node `properties.enabled: false`; the node is still present.                                                                   | ☐    |
| 3.2 | `PATCH {"enabled": true}`.                                                                    | `enabled: true` again.                                                                                                             | ☐    |
| 3.3 | Publish and approve BOM `1.3.0`, then `PUT …/extensions/bom {"version":"1.3.0", …}`.          | Still ONE BOM node; `properties.version` is `1.3.0`. No duplicate node, no extra edge.                                             | ☐    |
| 3.4 | Team owner blocks BOM (`PUT /api/v1/teams/{team}/extensions/policies/bom {"blocked": true}`). | The node stays (a block is policy, not an uninstall); the ST1 capability routes and tools are refused as before. Reset the policy. | ☐    |

## 4. Uninstall → gone, no dangling edges

| #   | Step                                                                                                                                                                                                                                                                                                                                                | Expected                                                                                 | Pass |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ---- |
| 4.1 | `DELETE …/extensions/bom` → `204`, then `GRAPH`.                                                                                                                                                                                                                                                                                                    | `widgets: []` (or only the other bundle from 2.5); exactly one edge per remaining child. | ☐    |
| 4.2 | DB: `select deleted_at is not null from graph_entity where kind='solus:widget' and attrs->>'slug'='bom'`.                                                                                                                                                                                                                                           | `true` for the BOM node (soft-deleted, ADR-027).                                         | ☐    |
| 4.3 | DB: live edges whose endpoint is missing or soft-deleted, for `P`: `select count(*) from graph_edge ge where ge.project_id = P and ge.deleted_at is null and (not exists (select 1 from graph_entity s where s.id=ge.src_id and s.deleted_at is null) or not exists (select 1 from graph_entity d where d.id=ge.dst_id and d.deleted_at is null))`. | `0`.                                                                                     | ☐    |
| 4.4 | The `extension.uninstall` data event.                                                                                                                                                                                                                                                                                                               | Payload carries `graph_node_id` of the removed node.                                     | ☐    |
| 4.5 | Reinstall BOM, then `GRAPH`.                                                                                                                                                                                                                                                                                                                        | A NEW node id (the soft-deleted one is not resurrected), one edge from the root.         | ☐    |

## 5. Self-healing and isolation

| #   | Step                                                                                                                          | Expected                                                                            | Pass |
| --- | ----------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ---- |
| 5.1 | With BOM installed, delete its `solus:widget` row directly in the DB (simulating an install that predates ST2), then `GRAPH`. | The node is recreated with the right attrs and edge — the read reconciles installs. | ☐    |
| 5.2 | Insert a stray `solus:widget` row with `attrs.slug = "ghost"` for `P`, then `GRAPH`.                                          | The stray is soft-deleted (no install backs it) and does not appear.                | ☐    |
| 5.3 | COMMUNITY (not on the team): `GRAPH` for `P`.                                                                                 | `404`.                                                                              | ☐    |
| 5.4 | Add COMMUNITY as a `viewer`, repeat.                                                                                          | `200` — reads are exempt from the member floor; the payload equals STAFF's.         | ☐    |
| 5.5 | COMMUNITY's own project: `GRAPH`.                                                                                             | Its own root and Live Bench (different ids), `widgets: []`.                         | ☐    |

## 6. SOL, checkers and fingerprinting never see the layer

| #   | Step                                                                                                                    | Expected                                                                                                                     | Pass |
| --- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ---- |
| 6.1 | With BOM installed and a synced source in `P`, ask SOL: "List every entity you can see in this project graph, by kind." | The answer and the streamed `context_used` never mention `Workspace`, `Live Bench`, `BOM` as entities, or any `solus:` kind. | ☐    |
| 6.2 | Ask SOL to run the checkers.                                                                                            | No warning names a workspace-layer node.                                                                                     | ☐    |
| 6.3 | Run a fingerprint pass (Sources → sync).                                                                                | No canonical part or match involves a `solus:` node.                                                                         | ☐    |

## 7. Migration and read-only posture

| #   | Step                                                                                              | Expected                                                                                                                     | Pass |
| --- | ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ---- |
| 7.1 | `uv run alembic current`.                                                                         | `c4d5e6f7a8b9 (head)`. `\d graph_entity` in psql shows the `domain` CHECK including `'workspace'`; same on `error_solution`. | ☐    |
| 7.2 | `uv run alembic downgrade b3f1c2d4e5a6` then `downgrade 9a1c4e7d2b30` while workspace rows exist. | The second downgrade REFUSES with "still holds workspace-domain rows"; upgrade back to head.                                 | ☐    |
| 7.3 | A v1 bundle published BEFORE this fix (if any exist): install it.                                 | `201` — migration `c4d5e6f7a8b9` stripped the defaulted tables from its stored manifest; the Store detail also renders it.   | ☐    |
| 7.4 | Attempt `PATCH`/`DELETE /api/v1/projects/P/entities/{root id}`.                                   | Refused (not `manual`); the row is untouched.                                                                                | ☐    |
