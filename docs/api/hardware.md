# hardware.md — Robot onboarding route plan (R5 · R1 · R2 · R4)

**Ticket:** SOLUSDEV-248 (ROBOT ONBOARDING R5 → R3 → R1 → R2 → R4), branch `SOLUSDEV-248-R15`.
**Status:** tier-1 route plan (ADR-032 — the MR review is the approval gate), implemented with the
ticket phase by phase. Product source: the ticket brief (no design spec exists in the repository).
**Authority:** DECISIONS.md ADR-034 (amendment 2026-09-06: structured Hardware-configs entries),
ADR-027 (free-string kinds, `project` domain), ADR-025 (project scoping), ADR-012 (fingerprint:
propose, never assert), ADR-031 §2 (telemetry is Pattern 2), CLAUDE.md §7 (tenant isolation;
ingested config and device input are untrusted). Architecture:
`docs/architecture/hardware-onboarding.md`. Wireflow: `docs/wireflows/hardware-onboarding.md`.
Bench sessions: `API.md` §2.10; the `.solus`: `solus.md`; Physical Robot roots: `workspace.md`.

All routes are under `/api/v1/projects/{project_id}/hardware` and resolve through `ProjectCtx`
(non-member → **404**, no existence leak). Reads need a resolvable project; writes need the
`member` role (viewer/share-only → `403`). Every write emits a data event; unknown fields → `422`.

## 1. Identity (shared by every route below)

A detected device is addressed by its **device ref** `"<transport>:<binding>"` where the transport
prefix is one of `usb`, `can`, `ble`, `bt`, `ip`, `ros2` and the binding is the transport's stable
identity (USB serial, adapter serial, BT address, MAC/IP, node name) — **never a tty path**. A
part on a bus is `"<device ref>/<address>"` (`usb:5B42134331/1`). These strings are the graph
`external_ref` the telemetry resolver matches `device_id` against. No driver or vendor name ever
appears in an identity; the driver lives in the config.

## 2. Hardware config (R5) — `solus.md` extension

A Physical Robot's configuration is one `.solus` Hardware-configs entry of kind `config`
(ADR-034 amendment): `solus_entries.payload` holds a `HardwareConfig` document validated on every
write (`schema_version: 1`, provenance on every leaf). The robot root's
`properties.hardware_config_ref` is that entry's id.

| Method | Path                                           | Purpose                                             | Success |
| ------ | ---------------------------------------------- | --------------------------------------------------- | ------- |
| GET    | `/robots/{robot_id}/config`                    | The robot's config (created empty on first read)    | `200`   |
| PUT    | `/robots/{robot_id}/config`                    | Replace the config; body is a full `HardwareConfig` | `200`   |
| POST   | `/robots/{robot_id}/parts`                     | Author a part under a category (R1 Authored)        | `201`   |
| POST   | `/robots/{robot_id}/parts/{part_id}/lifecycle` | Promote a part's lifecycle state                    | `200`   |

`GET` returns `{ "entry_id", "robot_entity_id", "config": HardwareConfig }`. `PUT` takes
`{ "config": HardwareConfig }`; the document's `robot_entity_id` must equal the path robot;
provenance on user edits is `user`. A robot that is not a live manual `physical_robot` in this
project → `404`.

`POST /parts` body: `{ "name": str ≤512, "category": one of sensors|actuators|controllers|
end_effectors|power|structure|wiring, "specs": { str: str|number|bool } ≤32 keys, "lifecycle"?:
planned|ordered|received|installed|live (default planned) }`. Creates a `kind="part"`,
`origin="manual"` entity under the category (`contains` edge), records the part in the config's
`parts` map with provenance `user`, and returns `{ "entity": Entity, "config_entry_id" }`.

`POST /parts/{part_id}/lifecycle` body `{ "state": … }` → the updated part config. Promotion never
changes the part's entity id or edges. A part not owned by this robot → `404`.

**HardwareConfig (summary; the Pydantic model is authoritative):**

```
schema_version: 1
robot_entity_id: UUID
identity?:   { kind: usb_serial|usb_can|ble|bt_classic|wifi|ethernet|ros2, binding, vid?, pid?,
               last_seen_path? (informational only) }
protocol?:   { driver_id: slug, params: { baud?, timeout_s?, protocol_version?, … } }
bus_map:     [ { protocol, address, part_entity_id?, model? } ]              (≤256)
parts:       { <part entity id>: { calibration?: { mode?: degrees|range_0_100|range_m100_100|
               linear|raw, values, source?, owner: repo|solus }, limits?: { values },
               telemetry: [ { name, unit? } ], firmware: {…},
               lifecycle: planned|ordered|received|installed|live } }        (≤256)
firmware:    { … }
disambiguated_by?: "user"
provenance:  { "<dotted leaf path>": { by: library|repo|user|sol|detected, source? } }
```

Every leaf path outside `schema_version`/`robot_entity_id`/`provenance` must have a provenance
record (`422` otherwise). Telemetry units derive from the calibration mode (`degrees→deg`,
`range_0_100→%`, `range_m100_100→%`, `linear→mm`).

## 3. Link suggestions (R5)

Emitted by the link-suggestion engine when a new part or device is observed (detection, library
import). **Precision over recall:** two plausible robots produce two rows; nothing auto-accepts.

| Method | Path                                  | Purpose                                        | Success |
| ------ | ------------------------------------- | ---------------------------------------------- | ------- |
| GET    | `/suggestions?status=pending`         | Suggestions for this project (default pending) | `200`   |
| POST   | `/suggestions/{suggestion_id}/accept` | Accept: attach the subject to the robot        | `200`   |
| POST   | `/suggestions/{suggestion_id}/reject` | Reject with optional `{ "reason" }`            | `200`   |

Row: `{ id, subject_ref, subject_kind: device|part, candidate_robot_id, confidence (0..1),
tier: high|medium|low, evidence: [ModalityMatch], reason, status, created_at, decided_at }`.
Tiers follow the CTR-08 bands: bus-enumerated ≤ 0.92, firmware-inferred ≤ 0.55, telemetry-shape
≤ 0.30. Accepting a suggestion resolves the sibling rows for the same subject as `superseded`.

## 4. Detection (R2)

| Method | Path                             | Purpose                                               | Success |
| ------ | -------------------------------- | ----------------------------------------------------- | ------- |
| GET    | `/detected`                      | Devices on this machine at whichever level is known   | `200`   |
| POST   | `/detected/{device_ref}/propose` | Interrogate safely and build a proposal               | `200`   |
| POST   | `/detected/{device_ref}/confirm` | Confirm accepted rows → robot, parts, config, session | `201`   |

`GET /detected` rows: `{ device_ref, transport, identity: { vid, pid, board_class, board?,
mcu_known, confidence }, level: transport|board|protocol|platform, protocol?: { driver_id,
confidence }, platform?: { name, confidence }, sessions: [ids] }`. Runner absent → `503
source_unavailable`, nothing faked.

`POST /propose` runs the Interrogator registry (safety class ping/listen only; commanding motion
is never part of a proposal) and the repo-config parsers over a linked local checkout when the
body carries `{ "repo_root"?: path }` (validated to an absolute, existing directory the runner may
read). Returns `{ device_ref, summary, rows: [ { id, subject, address, model?, proposed_function?,
confidence?, evidence: [ModalityMatch], provenance } ], repo_matches: [ { config_id, label,
source } ], disambiguation?: { question, options: [config_id] }, platform_candidates: [ {
platform_id, confidence } ] }`. Two matching repo configs → `disambiguation` is set and the
proposal names nothing as chosen.

`disambiguation.favoured` lists the matching configs whose declared per-part calibration
equals what the parts themselves carry (an interrogator's calibration signature, e.g. the
homing offsets a servo bus burned into its servos). Two wire-identical arms differ only there.
It orders the options (favoured first) and annotates the question; it never answers it — the
user still picks once.

Two API-side additions ride every proposal: `bound_repo_configs` lists the repo config ids
already bound to another device in this project (the repo layer's provenance `source` is the
config id), and those configs are removed from `repo_matches` — so the second, wire-identical
arm is offered the one remaining config with no question. `port_repair` is `null` when the repo
binds the path the device is on; `{ kind: "file", configured, actual, source, note }` when the
repo binds a different path; `{ kind: "command", actual, note }` when the repo binds no port at
all (the port comes from the command line). Solus does not edit the repo in this cycle — the
write-back through the confirmation gate is a later SOL action — and the note says so.

`POST /confirm` body: `{ "target": { "kind": "new", "name"? } | { "kind": "existing", "robot_id" },
"accepted": [ { "row_id", "function_name"?, "category"? (default "actuators") } ],
"repo_config_id"?, "repo_root"?, "start_session": bool (default true), "window_seconds"? }`.
The server re-runs the proposal at confirm time (the wire is the truth, never the client's
copy), then creates or reuses the robot through `PhysicalRobotService`, creates parts
(`external_ref = <device ref>/<address>`, `origin: manual`, provenance `detected` or `repo`) under
the chosen categories, writes the config through R5 (identity + protocol + bus map from the
`detected` layer; names, units and calibration from the chosen repo config in the `repo` layer;
`disambiguated_by: "user"` when the user chose among several matches), opens the session through
the driver registry, and returns `{ robot: Entity, part_ids, config_entry_id, session_id?,
session_error? }` — the robot exists even when the session did not start. Nothing is accepted
that the body did not name: an unknown `row_id` → `422`; two matching repo configs and no
`repo_config_id` → `422` carrying the question; a row already confirmed as a part of a robot →
`409` naming that robot (reconnecting a known machine needs no second robot); a device that
vanished → `404 device_not_found`. The proposal payload also carries `identity` (the
`TransportBinding` the confirm writes) so the client can show the binding it is about to bind.

### From a file — parts already in the graph (R2)

| Method | Path                              | Purpose                                                            | Success |
| ------ | --------------------------------- | ------------------------------------------------------------------ | ------- |
| GET    | `/unassigned?limit=&cursor=`      | Connector-sourced parts not owned by any live robot category       | `200`   |
| POST   | `/robots/{robot_id}/parts/attach` | Attach existing parts under a category: `{ entity_ids, category }` | `200`   |

`GET /unassigned` pages (≤100) over live entities from connected CAD/schematic/BOM sources whose
kind is a part-like kind (`part`, `component`, `cad_part`, `assembly` are the current set) and
that are not the target of a live manual `contains` edge from a robot category. `POST attach`
takes 1–64 entity ids (all live, this project, part-like; a part already under another robot →
`409`; already under this robot → skipped) and creates the manual `contains` edges from the
category node, records each part in the config (`lifecycle: planned`, provenance `user`) and
returns `{ attached: [ids], skipped: [ids], config_entry_id }`. Event: `hardware.parts_attached`.

## 5. Library (R4)

| Method | Path                              | Purpose                                        | Success |
| ------ | --------------------------------- | ---------------------------------------------- | ------- |
| GET    | `/library?q=&kind=part\|platform` | Lexical search over definitions                | `200`   |
| GET    | `/library/{kind}/{definition_id}` | Preview one definition                         | `200`   |
| POST   | `/library/platforms/{id}/import`  | Import a platform → new robot + parts + config | `201`   |
| POST   | `/library/parts/{id}/import`      | Import a part into `{ robot_id, category }`    | `201`   |

Definitions are Solus-curated YAML loaded in memory (no tenant data; vendor names are allowed in
definition files only). A platform composes part definitions; importing a platform imports its
parts with provenance `library`, then runs the link-suggestion engine against detected devices so
a library robot and the same machine on the wire reconcile to **one** robot.

## 6. Bench session extension (`API.md` §2.10)

`POST /bench/sessions` real-mode config gains `{ "provider": "robot", "robot_entity_id" }`: the
session opens from the robot's config (transport identity, driver id, driver params) through the
driver registry. `SerialRealConfig` keeps raw serial and gains optional `driver_id` and
`driver_params` (generic; no closed list of driver names). Session `device` echoes `device_ref`.

**Packets are keyed per part.** The resolver matches `packet.device_id` against `external_ref`,
and a part's external_ref is `<device ref>/<address>` — so the robot connection splits every
driver sweep by signal prefix and sends each part's signals under the part's own key
(`usb:5B42134331/6` for `gripper.position`), using only the config (a bound part's declared
telemetry names, or the drivers' unnamed `addr_<address>`). Signals no bound part claims keep the
device key and count as `unresolved`. A session against a robot with bound parts therefore shows
`counts.ingested > 0`; zero means the parts are not keyed (SOLUSDEV-248 live run, 2026-09-06).

## 7. Events

`hardware.config_updated {robot_id, entry_id}` · `hardware.part_created {robot_id, part_id,
category}` · `hardware.lifecycle_promoted {part_id, from, to}` · `hardware.suggestion_created
{suggestion_id, tier}` · `hardware.suggestion_decided {suggestion_id, decision}` ·
`hardware.proposal_built {device_ref, rows, disambiguation}` · `hardware.robot_confirmed
{robot_id, device_ref, parts}` · `hardware.library_imported {definition_id, robot_id}`.

## 8. Error catalogue

| HTTP | `error.code`         | Where                                                                   |
| ---- | -------------------- | ----------------------------------------------------------------------- |
| 401  | `unauthorized`       | missing/invalid JWT                                                     |
| 403  | `forbidden`          | write as viewer / share-only user                                       |
| 404  | `not_found`          | non-member project; unknown robot/part/suggestion/definition/device     |
| 409  | `conflict`           | suggestion already decided; robot not a manual `physical_robot`         |
| 422  | `validation_error`   | schema violation, missing provenance, unknown fields, oversize document |
| 503  | `source_unavailable` | detection/session routes when the local runner is absent                |
