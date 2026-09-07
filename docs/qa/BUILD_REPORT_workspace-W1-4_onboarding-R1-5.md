# Build report — Workspace W1–W4 and Robot onboarding R1–R5

**Date:** 2026-09-06 · **Branch:** `SOLUSDEV-248-R15` at `7e51697` (contains `origin/main` `d073749`).
Companion documents: `COMPLETION_SOLUSDEV-240-workspace-w1.md`, `COMPLETION_SOLUSDEV-242.md`,
`COMPLETION_SOLUSDEV-248-robot-onboarding.md`, and their `COWORK_QA_*` files.

Sources: the governing docs, the two completion reports, and a file-by-file read of the tree at
`7e51697` (branch `SOLUSDEV-248-R15`, which contains `origin/main` `d073749`). Line counts are
approximate; test counts are what pytest/vitest collect.

---

## A. Where the nine tickets live

| Tickets                                                           | Jira         | Commits                                              | On `origin/main`?         |
| ----------------------------------------------------------------- | ------------ | ---------------------------------------------------- | ------------------------- |
| **W1** Workspace rename + project `.solus` panel                  | SOLUSDEV-240 | `22ca168`                                            | yes                       |
| **W2** graph navigator, `.solus` as nodes ("W1 fix" + Phases 1–2) | SOLUSDEV-242 | `3003d51` (one squashed commit for all four phases)  | yes                       |
| **W3** service documents in Add (Phase 3)                         | SOLUSDEV-242 | `3003d51`                                            | yes                       |
| **W4** Physical Robot (Phase 4)                                   | SOLUSDEV-242 | `3003d51`                                            | yes                       |
| **R5, R3, R1, R2, R4** robot onboarding                           | SOLUSDEV-248 | 24 commits `901c47e`…`7e51697`, plus merge `c059170` | **no — this branch only** |

Numbering note: SOLUSDEV-242's docs number their phases 1–4 (navigator, `.solus` nodes, services,
robot). W1 is the earlier SOLUSDEV-240 ticket; SOLUSDEV-242's Phase 1 is the "W1 fix" that removed
W1's panel. The per-phase SHAs the 242 completion report cites (`52a6b06`, `c820825`, `ba4bd04`)
are not reachable in this repository — only the squash survives.

---

## B. Workspace W1–W4 — as built

### W1 — Graph → Workspace, and the project `.solus` (SOLUSDEV-240)

**Intent.** Rename the Context Model screen to Workspace and give every project a server-stored
`.solus`: five sections of entries (Hardware configs, Project details, Error logging,
Documentation, Code environment), edited from a left panel, writable by SOL.

**Governing docs.** ADR-034 amendment 2026-09-05 (third layer: project-level `.solus`, server-stored);
`docs/api/solus.md` (route plan); `docs/qa/COWORK_QA_SOLUSDEV-240.md`.

**Built.**

- API: `services/solus_config.py` (~280 lines: `ensure_solus_node`, `add_text_entry`,
  `add_artifact_entry`, `update_text`, `delete_entry`, limits 4000 chars / 500 entries per section);
  `routers/solus_config.py` under `/api/v1/projects/{id}/solus`; `models.py` `SolusSection`,
  `SolusEntryKind` (text | artifact | sol), `SolusEntry`; `.solus` created inside `create_project`'s
  transaction as a `graph_entity(kind=solus_config, domain=project, origin=manual)` and self-healed
  on first GET; migration `b7e2d4a9c1f0` (adds `project` to the domain enum, `artifacts.retained`,
  `solus_entries`).
- Imports are graph nodes: upload through the existing `POST …/artifacts`, then file the id; the
  artifact is marked `retained` (exempt from the TTL sweep) and wrapped in a `document` node edged
  `.solus →references→ document`. Typed text is not a node.
- SOL can write: the ungated `add_solus_entry(section, text)` builtin
  (`agent/tools/solus_entry.py`, author `sol`); the prompt tells SOL to file a source-naming result
  or nothing.
- Contracts: `Domain.PROJECT = "project"` added in `solus_contracts/connector.py`, mirrored in
  shared-types.
- Desktop: route id `graph` → `workspace`; `WorkspaceScreen.tsx` (renamed from `GraphScreen`);
  `useSolusConfig.ts`; `SolusPanel.tsx` (290 px left rail — **later deleted by W2**);
  `components/ui/ContextMenu.tsx` (the shared right-click menu, still used by W2–W4);
  client `getSolus` / add / patch / delete in `lib/api/resources.ts`.

**Routes.** `GET /solus` → `{entity_id, sections}`; `POST /solus/{section}/entries` (`text` or
`artifact`); `PATCH /solus/entries/{id}` (`{text}`; artifact → 409); `DELETE …/entries/{id}`.
Events `solus.entry_added|entry_updated|entry_deleted`.

**Tests.** API `test_solus_config.py` 12, `test_solus_entry.py` 2; desktop `useSolusConfig.test.ts`
5, `ContextMenu.test.tsx` 3 (the panel test became `useSolusNodes.test.tsx` in W2).

**Deferred by design.** S5 automatic error filing (a later ticket — nothing auto-files); SOL cannot
read imported PDF bytes (artifact byte-fetch deliberately inert, W0-04).

### W2 — the workspace navigator; `.solus` becomes real nodes (SOLUSDEV-242 Phases 1–2)

**Intent.** One animated graph navigator over the project's real entities, `.solus` centred at
(0,0) with its five sections as selectable graph nodes; W1's panel removed and its composers/menus
reused on node cards.

**Governing docs.** `docs/architecture/workspace-navigation.md` (Navigation and layout; types 1–2);
`docs/wireflows/workspace.md`; `docs/api/workspace.md` (layout routes); `docs/api/solus.md` Phase 2
amendment.

**Built.**

- Desktop navigator (all new): `navigation/GraphNavigator.tsx`, `useGraphNavigation.ts`,
  `graphIndex.ts` (deterministic forest: multi-parent containment picks one presentation parent,
  cycles broken in presentation only, cross-links projected onto visible ancestors), `GraphCard.tsx`,
  `GraphLinks.tsx`, `layout.ts`, `nodeTypes.ts`; `useWorkspaceGraph.ts` (complete snapshot,
  version/TTL cache; replaced `useGraphSummary`); `useWorkspaceLayout.ts` (write queue, deletion
  pruning, conflict retry); `WorkspaceScreen.tsx` rewritten (navigator + inspector + Add + robots).
  Rules: ≤24 cards per level with explicit paging; hover+wheel enters a level; leaves select without
  zooming; zoom never triggers a source sync; reduced motion honoured.
- `.solus` as nodes: `services/solus_graph.py` (`SolusGraph.ensure` under the project lock; five
  `solus_section` entities; entry identities; `contains` edges; the W1 `references` edge kept for
  Impact); desktop `useSolusNodes.tsx`, `SolusNodeContent.tsx`, `SolusComposer.tsx`,
  `solusActions.ts` (W1's import / Ask SOL / type / edit / delete handlers, moved). Text stays in
  `solus_entries`; nothing is duplicated as graph facts.
- Layout: `services/workspace_layout.py`, `routers/workspace_layout.py`; migrations
  `a3f242b9c610` (layout) and `b6f242d8e731` (idempotent data-only backfill of section/entry
  identities).

**Routes.** `GET /projects/{id}/workspace-layout` → `{version, positions{uuid:{x,y}}}`;
`PUT` with `{version, positions}` → new version; stale version 409; ≤5000 positions; unknown entity
404; event `workspace.layout_updated`. No new `.solus` route: GET's shape is unchanged except entries
now carry a real `entity_id`.

**Tests.** API `test_workspace_layout.py` 15, `test_solus_graph.py` 10; desktop
`useWorkspaceLayout` 8, `useWorkspaceGraph` 12 (+11 regression), `GraphNavigator` 10, `graphIndex` 8,
`useSolusNodes` 15, `workspaceFocus` 6, `WorkspaceScreen` 13, `graphCache` 5, `lib/api/workspace` 4.

**Deferred.** Add's service and hardware workflows (completed by W3 and R1); a Sources page named
as a W2 follow-up in the Home wireflow.

### W3 — service documents in Add (SOLUSDEV-242 Phase 3)

**Intent.** Add → _From a service_ lists the accounts connected in Home and their cached
documents/repos; selecting a new one creates a project node and starts its first sync; reselecting
only focuses. Dropdown reopen reuses the loaded listing; a cache-only read shows an honest
empty/missing state instead of spending provider quota.

**Governing docs.** `workspace-navigation.md` type 3 and "Phase 3 service attachment and live
refresh"; `wireflows/workspace.md` Add; `change-signal-spine.md` (probe/lease rules).

**Built.** Desktop `WorkspaceAdd.tsx` (tab shell with **From a service** and **Hardware** tabs — the
`hardware` ReactNode prop is the seam R1 later fills), `ServiceAccountPanel.tsx`,
`serviceCatalog.ts`, `useServiceCatalog.ts`, `serviceAttachments.ts`, `useServiceAttachments.ts`,
`workspaceSession.ts`, `useWorkspaceEvents.ts` + `lib/api/projectEvents.ts` (authenticated SSE on
`/projects/{id}/events`, `graph.changed` frames). API: Onshape connector/runtime/worker/httpcache and
`document_graph.py`, `routers/connections.py`, `routers/sources.py`, `graph/live.py`; migration
`c7f242e9a842` wraps legacy Onshape trees in `cad_document` roots.

**Routes.** No new route plan: rides the I1 connection routes plus a new optional `cache_only` query
parameter, the paginated `GET /entities` / `GET /relations`, and the existing SSE.

**Tests.** Desktop `serviceAttachments` 7, `serviceCatalog` 4, `WorkspaceAdd` 4, `useWorkspaceEvents`
3, `projectEvents` 4; API `test_onshape_call_budget.py` (new) plus edits to httpcache / onshape /
sources / graph_live tests.

**Stated limit.** OAuth connection alone does not register a provider webhook.

### W4 — the Physical Robot (SOLUSDEV-242 Phase 4)

**Intent.** `physical_robot` roots as independent manual graph instances with seven category
children (sensors, actuators, controllers, end_effectors, power, structure, wiring); default name is
the project name; confirmed deletion soft-deletes the containers and keeps parts as "unassigned";
no fingerprint auto-linking.

**Governing docs.** `workspace-navigation.md` type 4 and "Phase 4 manual robot ownership";
`wireflows/workspace.md` Hardware; `docs/api/workspace.md` route plan.

**Built.**

- API `services/physical_robots.py` (~290 lines): `ROBOT_CATEGORIES`, `PhysicalRobotService.create`
  ("one complete instance, without committing or calling a provider" — the R2 hook), `rename`,
  `delete`, `orphaned_robot_part_filter`; root `attrs = {"hardware_config_ref": null,
"transport_refs": null}` as nullable placeholders for R5/R3. `routers/entities.py`: `POST /entities`
  (only `physical_robot`), `PATCH`/`DELETE` with `If-Match` version (stale → 409 with the current
  version and name), `?orphaned_from_robot=true`. Guards: non-robot, non-manual or connector-owned
  nodes → 409, so `.solus`, connector and fingerprint nodes are unmutatable here. Events
  `workspace.robot_created|renamed|removed`. No migration.
- Desktop `robots/usePhysicalRobots.tsx`, `robotSession.ts`, `RobotNodeContent.tsx`,
  `RobotOrphans.tsx`, `lib/api/physicalRobots.ts`; the Add › Hardware tab held a single
  "Add Physical Robot" control.

**Tests.** API `test_physical_robots.py` 20 (asserts the null placeholders); desktop
`usePhysicalRobots.test.tsx` 19 (as of today), `physicalRobots.test.ts` 4.

**Deferred, named in the docs.** "R1 part creation is deferred"; "Hardware-config and transport
references are nullable placeholders for R5/R3, with no invented schemas. A single creation service
is the R2 hook"; generic manual CRUD beyond `physical_robot`.

---

## C. Robot onboarding R1–R5 — as built (SOLUSDEV-248, build order R5 → R3 → R1 → R2 → R4)

**Governing docs (authored on the branch as tier-1):** `docs/architecture/hardware-onboarding.md`,
`docs/api/hardware.md`, `docs/wireflows/hardware-onboarding.md`, `docs/contracts/telemetry-packet.md`
§2a; ADR-034 amendment 2026-09-06 (tier-2, approved in chat: a Hardware-configs entry may carry a
JSONB payload validated by the `HardwareConfig` model, one per Physical Robot, provenance on every
field). Standing rules that shaped every ticket: propose, never assert; empty beats invented; no
vendor in shared code (ratchet-enforced); addressing is generic `{protocol, address}`; the transport
does not know the protocol; every hardware gate has a fixture twin on a different machine.

### R5 — hardware config schema, lifecycle, link-suggestion engine

- `solus_api/hardware/config.py` (~300 lines): the `HardwareConfig` document — `identity`
  (`TransportBinding`: kind, binding, vid/pid, `last_seen_path`; `device_ref` =
  `<transport>:<binding>`, e.g. `usb:5B42134331`), `protocol` (`driver_id` + generic params),
  `bus_map` (`{protocol, address, part_entity_id, model}`), `parts` (calibration mode/values/owner,
  limits, telemetry channels with units, lifecycle planned → ordered → received → installed → live),
  `disambiguated_by`, and a per-leaf `provenance` map (`library | repo | user | sol | detected`)
  produced by `merge_layers` (later layer wins, provenance records who). Units derive from
  calibration mode (`degrees→deg`, `range_0_100→%`, `range_m100_100→%`, `linear→mm`). Bounds:
  64 KiB document, 256 bus entries.
- `store.py` (~430 lines): one `SolusEntry` of kind `CONFIG` per robot in W1's Hardware-configs
  section, validated on every write, mirrored as a `hardware_config` graph node with a `configures`
  edge (through W2's `SolusGraph`), `attrs.hardware_config_ref` set on the robot; `attach_part`,
  `create_part`, `promote`, unassigned-parts query, `attach_existing_parts` (409 if another robot
  owns it, cap 64).
- `links.py` (~315 lines): pure `suggest_links` over `ModalityMatch` evidence with five rules taking
  the best single score, never a sum — bus identity ≤ 0.92, free bus-map slot 0.80, whole bus map vs
  an identity-less robot 0.80, firmware ≤ 0.55, telemetry shape ≤ 0.30; floor 0.30; two plausible
  robots → two rows; nothing auto-accepts. Durable `hardware_suggestions` rows; accepting supersedes
  siblings.
- `models.py`: `SolusEntryKind.CONFIG`, `SolusEntry.payload` JSONB, `HardwareSuggestion`,
  `SuggestionStatus`. Migration `8f1c2a7d4e90` (chains off W3's `c7f242e9a842`); after the main sync
  the head is the merge revision `7e290e665c1f`.
- Routes (`/api/v1/projects/{id}/hardware`): `GET|PUT /robots/{id}/config`,
  `POST /robots/{id}/parts`, `POST /robots/{id}/parts/{part}/lifecycle`, `GET /suggestions`,
  `POST /suggestions/{id}/accept|reject`. All `ProjectCtx`, member on writes, events `hardware.*`.
- Tests: `test_hardware_config` 28, `test_store` 7, `test_links` 21, `test_hardware_router` 31.

### R3 — transports, protocol drivers, interrogators, reconnect, telemetry library

- Shared seams in `livebench/hardware/` (vendor-free): `channel.py` (`Channel`, `Frame`,
  `TransportRegistry` — a channel moves frames and does not know the protocol), `driver.py`
  (`ProtocolDriver` with declared transports and its own Pydantic params model, `DriverRegistry`),
  `interrogator.py` (`Interrogator` with safety passive | ping | listen, `InterrogatorRegistry`),
  `registries.py` (`default_registries()` = built-in transports + `plugins.load_all`), `replay.py`
  (a `Channel` over recorded frames so fixtures drive the same path), `connection.py`
  (`open_robot_connection`: transport → driver → reconnect → observers → windowing; the factory
  re-resolves the tty from the USB serial on every reconnect incarnation so a swapped port never
  swaps arms; `PartRoutingSource` keys each part's signals by `<device>/<address>`).
- Transports: `usb_serial.py` (bound by USB serial number), `usb_can.py`, `network.py` (UDP),
  `bluetooth.py` (BLE + Classic, honest when the stack is absent). `definitions/usb_boards.py` is
  data only (12 VID/PID rows; bridges flagged "MCU behind it not known").
- Plugins (`livebench/plugins/`, the only place vendor knowledge lives), roster in
  `PLUGIN_MODULES`: `feetech` (driver `feetech-sts`, interrogator `feetech-bus`; codec ported by
  file from SOLUSDEV-73 with golden frames; reads burned homing offsets as a calibration
  signature), `dynamixel` (`dynamixel-2`), `odrive` (`odrive-can`), `mavlink` (`mavlink`,
  hand-rolled v2 parser for HEARTBEAT/ATTITUDE/SERVO_OUTPUT_RAW), `lb06` (`lb06`, framing
  interrogator `serial-framing`), `jsonlines`, `raw`, `lerobot` (repo-config parser). `arduino/`
  holds the flash runner, off the roster by design.
- Bench: `provider: "robot"` session config (`RobotRealConfig{robot_entity_id, window_seconds}`)
  opens from the robot's config through the driver registry; `SerialRealConfig` gained generic
  `driver_id` + `driver_params`.
- `local.py` boundary the API loads: `detect_devices`, `propose_device`, `open_robot`.
- Telemetry library `libs/solus-telemetry/` (MIT): Python `Emitter`, MicroPython module, Arduino
  library + `NanoSixChannels` example, host parity check; one LB-06 JSON line per send, names
  `<part>.<quantity>`, units in the packet.
- Tests: seams/transports 88, plugins 152, `test_bench_robot_provider` 8, telemetry library 18.

### R1 — Add › Hardware, five cards, Authored end to end

- `features/graph/hardware/HardwareAddPanel.tsx` replaces the content of W4's Hardware tab through
  the existing `robots.hardware` seam: cards **Detected** (Devices on this machine), **From a file**
  (Parts from connected sources), **Library** (Curated parts and platforms), **Sourced** (disabled:
  "Sourcing (ST5) is not available yet."), **Authored** (Describe a part yourself).
  `hardware.constants.ts` holds the cards and per-category generic spec fields (never a product
  family); `HardwareCard.tsx`; `AuthoredPartModal.tsx` (name, robot target or create one, category,
  specs, lifecycle → `POST /parts`).
- `lib/api/hardware.ts` (~470 lines): the typed client; R5 shapes from the generated schema, R2/R4
  wire shapes hand-typed because those routes return `dict[str, Any]`.
- Tests: `HardwareAddPanel` 6, `AuthoredPartModal` 8, `vendorHygiene` 2, client 13.

### R2 — detection loop, repo config as a source, disambiguation, port repair, From a file

- `livebench/hardware/detection.py`: `enumerate_devices` (honest level — a bare USB bridge is
  reported at the transport level, confidence 0.30, `mcu_known False`), `interrogate_device`
  (candidate params, first answer wins, a busy port reads as silence), `propose` (rows, repo
  matches, `Disambiguation(question, options, favoured)`); `repo_config.py` (generic
  YAML/JSON/TOML shape reader + `RepoParserRegistry` + `match_configs`); the lerobot plugin parses
  `Motor(id, model, norm)` literals by AST and reads the machine-local calibration files; the wire
  calibration signature favours a config but never answers.
- API `hardware/detect.py` (~590 lines, service half): wire models incl. `PortRepair` (notice only:
  configured vs actual path, file or command, note — Solus never edits the repo),
  `propose_via_local`, `bound_repo_config_ids` + `exclude_bound` (the second arm is offered only the
  remaining configs), `_already_confirmed` (409 naming the owning robot), `reconcile_device`
  (suggestions against existing robots, never its own), `bind_device` (accepted suggestion: identity
  and protocol enter as `detected`, parts keyed `<device>/<address>`, parts that answered marked
  `live`), `confirm_proposal` (new robot via `PhysicalRobotService.create` or an existing one; parts
  under categories with `external_ref = <device>/<address>`; layers detected + repo; session started).
- Routes: `GET /detected`, `POST /detected/{ref}/propose`, `POST /detected/{ref}/confirm`,
  `GET /unassigned`, `POST /robots/{id}/parts/attach`.
- Desktop: `DetectedModal.tsx`, `ProposalView.tsx` (nothing is sent before Confirm; only accepted
  or edited rows travel), `detected.ts`, `FromFileModal.tsx`.
- Tests: `test_hardware_detect` 22, `test_hardware_attach` 9; livebench detection/repo-config/
  parser/local/open_robot 47; desktop `DetectedModal` 10, `FromFileModal` 6.

### R4 — parts and platform library

- `hardware/library.py` (~340 lines): YAML definitions loaded once in memory (no table, ADR-033
  untouched), lexical search, `part_config`; 18 parts and 6 platforms under
  `hardware/definitions/{parts,platforms}`; `definitions/vendor/` is the typed ingest seam for
  vendor-shipped definition files, seeded empty. `library_router.py`: `GET /library?q=`,
  `GET /library/{kind}/{id}`, `POST /library/platforms/{id}/import` (robot + parts + config,
  provenance `library`, then reconciliation through the link engine — a matching detected device
  yields one pending suggestion, never a second robot), `POST /library/parts/{id}/import`.
- Desktop `LibraryModal.tsx` (~500 lines): search with Parts/Platforms groups, preview (specs;
  platform part list and gear-ratio table), import a part into a robot with a category, or a
  platform as a new robot, with the pending-suggestion line.
- Tests: `test_library` 24, `test_library_router` 19; desktop `LibraryModal` 9.

### Generalisation proofs (Phase 6)

- `livebench/tests/lb_three_machines_test.py`: a flight controller over UDP, a CAN drive base and
  a bare line-protocol rover onboard through one branch-free sequence; a `sys.setprofile` tracer
  asserts the set of non-plugin modules is identical across the three; every packet carries a part
  key.
- Vendor ratchets: `lb_vendor_hygiene_test.py` (shared trees `hardware`, `recognition`,
  `telemetry`, `local.py`; regex over feetech|dynamixel|lerobot|sts3215|so-101|px4|odrive|mavlink|
  unitree|ur5e|arduino|teensy|esp32|ch343|… with no allowlist; a fresh interpreter importing the
  detection/connection/registries loads no plugin module), `test_vendor_hygiene_api.py` (same regex
  over `hardware/*.py` and `livebench/*.py`, definitions excluded by construction), desktop
  `vendorHygiene.test.ts` (adds tty paths and `.ino`). All three run in CI; the CI change filter
  now also covers `libs/`.

---

## D. How R1–R5 hang off W1–W4 (the four seams, none of W's contracts changed)

1. **`PhysicalRobotService.create` is the R2 hook.** It now has three callers with the identical
   transaction: W4's manual Add, R2's confirm, R4's platform import. No second creation path.
2. **`WorkspaceAdd`'s `hardware` ReactNode.** W4 filled it with a one-button component; R1 swapped
   only the fill (`usePhysicalRobots.tsx` now returns `HardwareAddPanel`). `WorkspaceAdd.tsx` is
   untouched by 248.
3. **`attrs.hardware_config_ref`.** W4's null placeholder; R5's store is the only writer.
   `transport_refs` remains a null placeholder with no writer (R3 keeps transports in the config).
4. **The Hardware-configs section is the config's home.** W1's `SolusEntryKind` gained `CONFIG`
   and a JSONB `payload`; W2's `SolusGraph.attach_entry` routes CONFIG entries to a
   `hardware_config` node with the same `contains` edge as any entry; W1's PATCH refuses CONFIG
   (409) and W1's GET shape is preserved (`payload` only for CONFIG).

Identity end to end: a device is `<transport>:<binding>` (USB serial, never a tty path); a part is
`<device>/<address>` and that string is the part's `external_ref`, which is what the telemetry
resolver matches `packet.device_id` against — so the driver's sweep is split per part before it
reaches the resolver.

---

## E. Verification status and gaps

**Verified on hardware (two six-servo arms, live API):** R5 provenance layers from real confirm and
accept; R3 both arms by USB serial at 1 Mbaud, sessions from config, every packet resolved (zero
unresolved), joints in `deg`, gripper in `%`; R2 enumerate → six rows at 0.92 with repo names and
calibration → one disambiguation question with the wire favouring one config → confirm, second arm
offered only unbound configs, 409 on re-confirm; R4 import → one suggestion → accept → bound and
live, no second robot. Repeated after the main sync.

**Verified on fixtures / CI only:** all desktop flows (vitest, not driven by hand), CAN and UDP
transports, replay path, reconnect identity re-resolution, telemetry-library parity, the three-machine
proof and the ratchets.

**Not verified:** unplug/replug and USB port swap on the bench, flashing a Nano with the library,
W3 against a live provider in this session. W1–W4 themselves were verified in their own sessions
(their QA files), not re-run here beyond their suites passing on the merged tree.

**Gaps found while compiling this report (not yet fixed):**

- **ADR-027 was never amended in prose.** `docs/api/solus.md` and the W1 completion report cite an
  "ADR-027 amendment 2026-09-05 (the `project` domain)", but DECISIONS.md still lists the original
  five domains; the amendment exists only as a comment in `solus_contracts/connector.py`. Tier-2:
  needs an in-chat approved text before editing DECISIONS.md.
- The 242 completion report's per-phase SHAs are unreachable (squash); attribution rests on docs.
- `docs/qa/COWORK_QA_workspace-shell.md` predates the rename and still says "Context Model".
- The `docs/design/screens/SPEC.md` citations were corrected on this branch only; main still
  carries the dangling reference.
- The 248 completion report miscounts `test_hardware_detect` (22, not 28) — fixed on approval.

---

## F. Numbers

| Area                                                                            | Tests                                      |
| ------------------------------------------------------------------------------- | ------------------------------------------ |
| W1 API + desktop                                                                | 12 + 2 API; 5 + 3 desktop                  |
| W2 API + desktop                                                                | 25 API; 92 desktop                         |
| W3 desktop (+ API edits)                                                        | 22 desktop; 1 new API file                 |
| W4 API + desktop                                                                | 20 API; 23 desktop                         |
| R1–R5 API (`test_hardware_*`, store, links, library\*, robot provider, hygiene) | 170 collected                              |
| R1–R5 livebench (seams, transports, detection, plugins, proofs)                 | ~295 collected                             |
| Telemetry library                                                               | 18                                         |
| R1–R5 desktop                                                                   | 54                                         |
| Whole tree after the main sync                                                  | API 4036 · fast suites 1344 · desktop 2815 |
