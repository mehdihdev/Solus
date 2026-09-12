# Solus Workspace and physical hardware redesign — Phase 2 execution plan

**Last updated:** 2026-09-07. Scope: the complete approved Workspace and physical hardware redesign, recorded in the governing architecture, wireflow, API, local-state and hardware-config schema documents listed below. The original user packet and in-session design review are the approval record. Phase 1, the exact ADR-034/private-state amendment, and the five-ticket split are approved by the user's “yes i do approve”; numbering is authorized by “just go up from 250.” This plan adds no design approval gate. The orchestrator installs ownership manifests and dispatches implementation. This is the saved execution plan, not a completion report.

Work in `/home/beeboss/Solus`. The feature stack is:

| Unit | Ticket and feature branch                    |
| ---- | -------------------------------------------- |
| A    | `SOLUSDEV-251-hardware-ownership-config`     |
| B    | `SOLUSDEV-253-discovery-connection-recovery` |
| C    | `SOLUSDEV-254-workspace-canvas-integrations` |
| D    | `SOLUSDEV-255-inspector-graph-context`       |
| E    | `SOLUSDEV-256-hardware-onboarding-qa`        |

`SOLUSDEV-252-sol-p1` is occupied by unrelated work and is excluded. Start each subsequent ticket branch from the previous verified feature branch; the final E branch contains the integrated stack. Do not push, create an MR, merge to main, change the QA checkout's branch, or rewrite human-seen history. A worktree, if used, branches only from its own ticket's feature branch into that ticket's namespace. Each ticket retains its own reviewable diff against the previous branch.

Governing material read: root `AGENTS.md`; `DECISIONS.md` (particularly ADR-001/005/008/012/016/019/020/021/025/027/028/030/031/032/034); `docs/architecture/workspace-navigation.md`, `hardware-onboarding.md`, `local-connections.md`, `change-signal-spine.md`; `docs/api/workspace.md`, `hardware.md`, `solus.md`; `docs/wireflows/workspace.md`, `hardware-onboarding.md`; `apps/desktop/CLAUDE.md`; `docs/contracts/focus.md`, `local-state.md`; the existing local-state twins in `packages/contracts/python/solus_contracts/local_state.py` and `packages/shared-types/src/local-state.ts`; `docs/qa/BUILD_REPORT_workspace-W1-4_onboarding-R1-5.md`; `docs/CODEMAPS/workspace.md`; `.codex/agents/planner.toml`; `.claude/commands/plan.md`; and applicable `.claude/rules/common/` plus Python/TypeScript testing rules. The migrated `source-command-plan` skill supplies the planning workflow, subordinate to the settled approval and repository protocol. Directory `AGENTS.md` files are absent in the relevant observed directories; the existing desktop `CLAUDE.md` supplies its directory-specific rules. The approved review supplies amendments to existing, present governing designs; it is not a missing-spec gap. The build report's ADR-027 gap is stale and already resolved.

Maintain these seams: project-scoped graph entities/edges, `ProjectCtx` and standard API envelopes, `EntityResolver.resolve(project_id, device_id)`, current `LiveConnection`/`PacketSource`/telemetry packets, plugin `Channel`/driver/interrogator/repo-parser registries, shared Focus with real entity UUIDs, existing `MessageCreate.mentions` and SOL conversation/tool admission, and the existing artifact/`.solus` entry workflow. Their definitions do not change. Only the approved private hardware-state contract is new; API-local HardwareConfig v2 is implemented without broadening frozen contracts.

Before A implementation, the orchestrator lands the already-approved governance/private-state contract and parity fixtures in a dedicated commit, and updates the tier-1 hardware/workspace/solus/local-state designs to match the approved review. ADR-034 was reported committed as `366e8fe` while planning. These protected changes are orchestrator-only prerequisites, never delegated worker assignments. No worker edits `DECISIONS.md`, `packages/contracts/`, `packages/shared-types/`, instructions, hooks, settings, secrets files, or CI. Further protected changes outside the approved text remain proposals, not implementation tasks.

## 1. Task decomposition

| Task | Name                                         | One-line scope                                                                                                                                                                                          | Contracts implemented or consumed                                                                       | Size |
| ---- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ---- |
| A0   | Baseline and migration inventory             | Capture pre-change responsiveness/creation behavior and migration anomaly inventory without mutating live project content.                                                                              | Approved acceptance spans; graph/config persistence invariants                                          | M    |
| A1   | Entity-owned configuration and ownership     | Implement strict v2 storage, migration, project-owned loose parts, versioned assignment, source-safe bindings, idempotent save-before-connect, and existing route adapters as one coupled backend unit. | HardwareConfig v2; ProjectCtx/envelope; graph entity/edge; EntityResolver; existing runtime config seam | L    |
| A2   | Private hardware sources in desktop MAIN     | Implement the approved local file's sender-gated picker/import storage and authenticated scope plumbing; expose only portable references to shared requests.                                            | Approved `HardwareLocalState` TS/Python twins; ADR-034 file rules                                       | M    |
| A3   | A integration and typed clients              | Integrate MAIN references with the authenticated local reader, regenerate API output, and give existing UI callers strict entity/config/parent APIs with compatibility regressions.                     | A1 route shapes; A2 IPC reference contract; existing typed client                                       | M    |
| A4   | A verification and handoff                   | Verify migrations, race/isolation cases, API/runtime compatibility and private-state security; resolve reviews and document the ownership/config release.                                               | Contract suites; AGENTS §6/§7                                                                           | M    |
| B1   | Port ownership, discovery and recovery       | Add one runner-owned port lease across probing/raw/sessions/reconnect; preserve typed faults, bounded cancellation, observation generations and safe re-resolution.                                     | Existing local runner, Channel, Interrogator, LiveConnection and PacketSource                           | L    |
| B2   | Evidence and reviewed proposals              | Stage graph/config/artifact evidence and plugin parsing; cache immutable inputs by digest and revalidate material evidence at confirmation without overwriting saved values.                            | A1 config/ownership; B1 observation/fault semantics; unchanged plugin registries                        | L    |
| B3   | B verification and handoff                   | Prove contention, cancellation, replug, ambiguous identities, honest readiness and plugin generality with fixtures and available live passive checks.                                                   | Telemetry/resolver contract; vendor-hygiene ratchets                                                    | M    |
| C1   | Integration identity and layout metadata     | Persist available account display metadata separately from identity, expose scoped groups, and extend layout only as documented for persistent group placement.                                         | AccountInfo and source identity; ProjectCtx; existing layout version contract                           | M    |
| C2   | Canvas and Add surface                       | Implement responsive opaque Add, Integrations groups, body dragging, local pan/zoom, explicit hierarchy navigation and retained-part reveal with bounded rendering.                                     | C1 DTOs/layout; shared Focus; A1 ownership reads; existing caches/SSE                                   | L    |
| C3   | C verification and handoff                   | Verify labels/focus/responsiveness, account boundaries, saved coordinates/conflicts, zero passive provider calls and representative graph frame times.                                                  | Focus/layout/provider-quota invariants                                                                  | M    |
| D1   | Contextual notes and imports                 | Add validated optional entity context to existing `.solus` entry/tool paths using manual references edges and existing artifact rules.                                                                  | Existing entry/artifact APIs; ToolRegistry never-raises; ProjectCtx                                     | M    |
| D2   | Consistent node inspector                    | Render immediate cached summaries, progressive evidence/relationships, visible context actions and explicit node-scoped SOL submission.                                                                 | D1 entry context; MessageCreate.mentions; existing chat store; Guide/Expert and action confirmations    | L    |
| D3   | D verification and handoff                   | Prove context ownership, stale selection isolation, no model call on click, preserved budgets/confirmations and malicious document/output handling.                                                     | SOL and graph authorization; artifact and tool invariants                                               | M    |
| E1   | Two-screen Hardware flow                     | Replace the five entry cards with information selection and one review screen; blank required names, optional parent, focused questions, saved/available/receiving/setup states and retry.              | A/B APIs, A2 local references, C shell and D context actions                                            | L    |
| E2   | Running application, physical QA and metrics | Exercise the actual desktop, both LeRobot arms before/after normal `.solus` context, replay fixture gaps, measure all required responsiveness spans and fix evidenced issues.                           | Full approved acceptance matrix; unchanged hardware safety/telemetry contracts                          | L    |
| E3   | Integrated verification and final handoff    | Complete all reviews/checks, update governing docs/codemaps, produce measured report and self-contained live/fixture/unverified Cowork QA, integrate/clean task branches.                               | AGENTS Phase 4/5 and ADR-021                                                                            | M    |

A1 intentionally stays one unit: `models.py`, `HardwareConfig`, migration transforms, storage, ownership and current confirm/library consumers share changing invariants. Splitting these among simultaneous writers would create an unstable interface and migration races. A1 may deliver sequential local checkpoints internally; it is not permission to split its files between competing workers.

## 2. Dependency graph

- A0 depends on the existing application and fixture/reference setup; capture before behavior changes. Missing physical access does not stop fixture/API baseline capture, but leaves the missing span explicitly unmeasured.
- A1 depends on A0 and the orchestrator's approved contract/design prerequisite.
- A2 depends on the approved private-state contract/fixtures and frozen IPC scope agreed by the orchestrator. A2 has no dependency on A1 implementation.
- A3 depends on A1 and A2. A4 depends on A3.
- B1 depends on A4. B2 depends on B1. B3 depends on B2.
- C1 depends on B3 in the chosen serial branch stack. Its functional dependency is A1, but it waits to avoid shared generated output and cross-ticket integration overhead.
- C2 depends on C1. C3 depends on C2.
- D1 depends on C3. D2 depends on D1. D3 depends on D2.
- E1 depends on D3 and all A/B APIs. E2 depends on E1. E3 depends on E2.
- Each implementation task's corrections depend on its fresh review findings; verification does not silently waive a failing implementation task.

## 3. Sequential vs parallel decision

A1 and A2 may run in parallel after the private contract and MAIN request/reference scope are frozen. Their ownership below is disjoint: A1 owns Python/backend/runtime compatibility, while A2 owns Electron MAIN/preload. Neither changes the other's API. A3 is the single sequential integration point and owns generated OpenAPI/renderer output, avoiding concurrent regeneration.

All other implementation tasks are sequential by default. B1 and B2 both need `livebench.local`, detection and API proposal code; C1 and C2 meet at changing metadata/layout DTOs; C2, D2 and E1 all touch `WorkspaceScreen`/Add/inspector composition. Sequence these instead of juggling shared files. The technically possible B/C feature parallelism is deliberately not selected: the approved five-ticket split needs separately reviewable branches and both touch shared API output/doc currency, while runtime work may refine visible recovery data.

Fresh-context code review, security review, and applicable Python/TypeScript/database review can run concurrently when read-only, against the same fixed integrated diff. Run no write worker while those reviews use their fixed snapshot; findings return to the owning implementation task. Documentation is orchestrator-owned and sequential with review fixes. The available team limit is four concurrent agents including the orchestrator.

## 4. Execution mode per task

| Tasks              | Mode                                                                                                                                                                              |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A0                 | Orchestrator/in-process read-only test and profiling unit; no physical motion, flashing, deployment or live data cleanup.                                                         |
| A1                 | In-process API worker by default, owning the complete coupled unit; if isolated long-running execution is needed, `SOLUSDEV-251/entity-config-ownership` from A's feature branch. |
| A2                 | In-process desktop worker after contract stabilization; optional worktree `SOLUSDEV-251/private-hardware-state` from A's feature branch.                                          |
| A3                 | Orchestrator or one in-process integration worker, sequential after A1/A2 integrate.                                                                                              |
| B1, B2             | One sequential runtime worker, in process; optional `SOLUSDEV-253/discovery-recovery` for an isolated long build.                                                                 |
| C1, C2             | Sequential in-process API then frontend units; optional `SOLUSDEV-254/canvas-integrations` for the long renderer build.                                                           |
| D1, D2             | Sequential in-process API then frontend units; optional `SOLUSDEV-255/inspector-context` for the long renderer build.                                                             |
| E1                 | In-process frontend unit; optional `SOLUSDEV-256/hardware-flow` for the long UI build.                                                                                            |
| E2                 | In-process e2e-runner and orchestrator; actual hardware interaction stays in the authorized current local application/project.                                                    |
| A4, B3, C3, D3, E3 | In-process fresh code/security/language review subagents plus orchestrator for validation, docs and integration.                                                                  |

Every worker receives this task's concrete acceptance cases, the frozen interfaces, exact manifest, the instruction to write failing tests first, and: “You are not alone in the codebase. Do not revert other agents' edits; accommodate their changes. Edit only assigned files; return out-of-scope needs to the orchestrator.” No worker owns protected governance or remote git actions.

## 5. File ownership map

All paths are relative to `/home/beeboss/Solus`. Existing paths were observed. A path described as **new** is an intentional narrow addition in an existing feature directory, not an instruction to recreate an old deleted implementation. Migration globs reserve only new ticket-named revisions; do not edit historical migration files. Before dispatch, the orchestrator checks current changes and materializes one `.list` per active task from these blocks.

The requested manifest path is `.Codex/state/ownership/<task-id>.list`. The actual installed H12 scripts in BOTH `.codex/hooks/` and `.claude/hooks/` read `.claude/state/ownership/*.list`; mirror the same approved contents there so enforcement runs. Do not edit hooks or settings. H12 checks the union of active manifests rather than per-agent attribution, so the orchestrator must also compare each returned diff to that worker's assignment. Remove manifests only after the task's changes are integrated and verified; activate a successor's overlapping manifest only once its predecessor has relinquished the files. The planner has only `/tmp` write ownership and therefore leaves installation to the orchestrator.

### A0.list — baseline artifact only

```text
docs/qa/PERFORMANCE_SOLUSDEV-251_baseline.md
docs/qa/MIGRATION_SOLUSDEV-251_preflight.md
```

### A1.list — coupled API/configuration/migration implementation

```text
packages/api/src/solus_api/models.py
packages/api/src/solus_api/hardware/config.py
packages/api/src/solus_api/hardware/store.py
packages/api/src/solus_api/hardware/ownership.py
packages/api/src/solus_api/hardware/migration.py
packages/api/src/solus_api/hardware/operations.py
packages/api/src/solus_api/hardware/runtime.py
packages/api/src/solus_api/hardware/bindings.py
packages/api/src/solus_api/hardware/hardware_router.py
packages/api/src/solus_api/hardware/detect.py
packages/api/src/solus_api/hardware/links.py
packages/api/src/solus_api/hardware/library.py
packages/api/src/solus_api/hardware/library_router.py
packages/api/src/solus_api/services/physical_robots.py
packages/api/src/solus_api/services/solus_config.py
packages/api/src/solus_api/services/solus_graph.py
packages/api/src/solus_api/routers/entities.py
packages/api/src/solus_api/livebench/bench_router.py
packages/api/src/solus_api/graph/resolver.py
packages/api/migrations/versions/*_solusdev_251_*.py
packages/api/tests/test_hardware_config.py
packages/api/tests/test_hardware_config_migration.py
packages/api/tests/test_hardware_operations.py
packages/api/tests/test_hardware_ownership.py
packages/api/tests/test_hardware_router.py
packages/api/tests/test_hardware_attach.py
packages/api/tests/test_hardware_detect.py
packages/api/tests/test_store.py
packages/api/tests/test_links.py
packages/api/tests/test_library.py
packages/api/tests/test_library_router.py
packages/api/tests/test_physical_robots.py
packages/api/tests/test_bench_robot_provider.py
packages/api/tests/test_bench_hardware_provider.py
packages/api/tests/test_resolver.py
packages/api/tests/test_solus_config.py
packages/api/tests/test_solus_graph.py
packages/api/tests/test_models.py
packages/api/tests/fixtures/hardware_migration/
livebench/src/livebench/hardware/connection.py
livebench/src/livebench/local.py
livebench/tests/lb_robot_test.py
livebench/tests/lb_three_machines_test.py
```

New narrow modules in A1: `ownership.py`, `migration.py`, `operations.py`, `runtime.py`, `bindings.py`; create only those warranted by the coupled responsibilities, rather than five empty abstractions. New tests: migration/operations/ownership/hardware-provider and their fixture folder. Existing shared config imports must remain compatible through an explicit resolved runtime view; no plugin learns DB ownership. A1 owns `local.py` only for v2 runtime compatibility, not B's discovery rewrite. Its new idempotency persistence uses a bounded project/user/operation key and reviewed payload identity; existing billing idempotency tables are not a general operation store.

### A2.list — MAIN local-state consumer and IPC

```text
apps/desktop/src/main/hardwareLocalState.ts
apps/desktop/src/main/hardwareLocalState.test.ts
apps/desktop/src/main/hardwareSources.ts
apps/desktop/src/main/hardwareSources.test.ts
apps/desktop/src/main/index.ts
apps/desktop/src/preload/index.ts
apps/desktop/src/preload/index.d.ts
```

The four `hardware*` files are new. Reuse `localState.ts`, `projectFolder.ts` and `senderGate.ts` as read-only patterns/dependencies. Return a required change to them to the orchestrator instead of expanding A2 silently. MAIN owns canonicalization, picker authorization, private atomic writes and scoped reply; renderer-selected paths are not trusted as file-read permission.

### A3.list — integrate references and regenerate clients

```text
packages/api/src/solus_api/hardware/local_sources.py
packages/api/src/solus_api/hardware/detect.py
packages/api/src/solus_api/hardware/hardware_router.py
packages/api/tests/test_hardware_local_sources.py
packages/api/tests/test_hardware_detect.py
packages/api/tests/test_hardware_router.py
packages/api/openapi.json
apps/desktop/src/renderer/src/lib/api/schema.ts
apps/desktop/src/renderer/src/lib/api/hardware.ts
apps/desktop/src/renderer/src/lib/api/hardware.test.ts
apps/desktop/src/renderer/src/lib/api/physicalRobots.ts
apps/desktop/src/renderer/src/lib/api/physicalRobots.test.ts
```

`local_sources.py` and its test are new. A3 starts only after A1 relinquishes its overlapping API paths. The local reader runs through the existing runtime-optional local runner topology; when runner support is absent the cloud cannot open local sources. The request sends opaque source/config IDs and authenticated scope, not raw local paths. A3 verifies the old UI's intentional name validation failures are actionable until E migrates creation screens; no auto-names are reintroduced for compatibility.

### B1.list — runner lifecycle and typed recovery

```text
livebench/src/livebench/hardware/leases.py
livebench/src/livebench/hardware/observations.py
livebench/src/livebench/hardware/channel.py
livebench/src/livebench/hardware/detection.py
livebench/src/livebench/hardware/usb_serial.py
livebench/src/livebench/hardware/usb_can.py
livebench/src/livebench/hardware/network.py
livebench/src/livebench/hardware/bluetooth.py
livebench/src/livebench/hardware/connection.py
livebench/src/livebench/local.py
livebench/src/livebench/recognition/passive.py
livebench/src/livebench/telemetry/reconnect.py
livebench/src/livebench/telemetry/serial_source.py
packages/api/src/solus_api/livebench/sessions.py
packages/api/src/solus_api/livebench/bench_router.py
packages/api/src/solus_api/hardware/detect.py
packages/api/src/solus_api/hardware/hardware_router.py
packages/api/tests/test_sessions.py
packages/api/tests/test_bench_router.py
packages/api/tests/test_hardware_detect.py
packages/api/tests/test_hardware_router.py
livebench/tests/lb_port_leases_test.py
livebench/tests/lb_hotplug_test.py
livebench/tests/lb_detection_test.py
livebench/tests/lb_reconnect_test.py
livebench/tests/lb_serial_source_test.py
livebench/tests/lb_connection_test.py
livebench/tests/lb_robot_test.py
```

`leases.py`, `observations.py`, lease/hotplug tests are new; `lb_detection_test.py` follows the existing observed livebench test naming. If an OS event watcher requires another file, assign one explicit path under `hardware/` before editing; bounded polling is the documented fallback. No per-device process/container or cloud ARQ local I/O.

### B2.list — reviewed evidence and plugin parsing

```text
packages/api/src/solus_api/hardware/detect.py
packages/api/src/solus_api/hardware/hardware_router.py
packages/api/src/solus_api/hardware/evidence.py
packages/api/src/solus_api/hardware/local_sources.py
packages/api/src/solus_api/hardware/links.py
livebench/src/livebench/hardware/detection.py
livebench/src/livebench/hardware/repo_config.py
livebench/src/livebench/local.py
livebench/src/livebench/definitions/usb_boards.py
livebench/src/livebench/plugins/lerobot/lerobot_parser.py
livebench/src/livebench/plugins/feetech/feetech_interrogator.py
packages/api/tests/test_hardware_evidence.py
packages/api/tests/test_hardware_detect.py
packages/api/tests/test_hardware_router.py
packages/api/tests/test_links.py
packages/api/tests/test_hardware_local_sources.py
livebench/tests/lb_detection_test.py
livebench/tests/lb_repo_config_test.py
livebench/tests/lb_lerobot_parser_test.py
livebench/tests/lb_feetech_interrogator_test.py
livebench/tests/lb_three_machines_test.py
livebench/tests/fixtures/hardware_redesign/
```

`evidence.py`, its test and `hardware_redesign/` fixtures are new. Improve only supported definitions/recognition demonstrated by reliable provider/device evidence; do not invent a broad new driver roster. Individual arm data never enters these application files. Existing vendor-hygiene suites are read/run unchanged unless a concrete legitimate test expectation needs its own assignment.

### C1.list — account metadata and layout server boundary

```text
packages/api/src/solus_api/models.py
packages/api/src/solus_api/schemas.py
packages/api/src/solus_api/connectors/onshape.py
packages/api/src/solus_api/services/connections.py
packages/api/src/solus_api/routers/connections.py
packages/api/src/solus_api/routers/sources.py
packages/api/src/solus_api/services/workspace_layout.py
packages/api/src/solus_api/routers/workspace_layout.py
packages/api/migrations/versions/*_solusdev_254_*.py
packages/api/tests/test_connections.py
packages/api/tests/test_sources.py
packages/api/tests/test_onshape_connector.py
packages/api/tests/test_workspace_layout.py
packages/api/tests/test_workspace_service_phase3.py
packages/api/tests/test_onshape_call_budget.py
```

Persist readable names from existing authorized responses; no OAuth scope expansion. Group on proven provider/account identity, never display names. Project members see attached source metadata, not another member's private account catalog. Movable presentation-group coordinates, if required, use a separately typed map rather than fake entity UUIDs and must be included in the tier-1 layout amendment first.

### C2.list — canvas and responsive Add

```text
apps/desktop/src/renderer/src/features/graph/navigation/
apps/desktop/src/renderer/src/features/graph/WorkspaceScreen.tsx
apps/desktop/src/renderer/src/features/graph/WorkspaceScreen.test.tsx
apps/desktop/src/renderer/src/features/graph/WorkspaceAdd.tsx
apps/desktop/src/renderer/src/features/graph/WorkspaceAdd.test.tsx
apps/desktop/src/renderer/src/features/graph/ServiceAccountPanel.tsx
apps/desktop/src/renderer/src/features/graph/ServiceAccountPanel.test.tsx
apps/desktop/src/renderer/src/features/graph/serviceCatalog.ts
apps/desktop/src/renderer/src/features/graph/serviceCatalog.test.ts
apps/desktop/src/renderer/src/features/graph/useServiceCatalog.ts
apps/desktop/src/renderer/src/features/graph/serviceAttachments.ts
apps/desktop/src/renderer/src/features/graph/serviceAttachments.test.ts
apps/desktop/src/renderer/src/features/graph/useServiceAttachments.ts
apps/desktop/src/renderer/src/features/graph/useWorkspaceLayout.ts
apps/desktop/src/renderer/src/features/graph/useWorkspaceLayout.test.ts
apps/desktop/src/renderer/src/features/graph/workspaceFocus.ts
apps/desktop/src/renderer/src/features/graph/workspaceFocus.test.ts
apps/desktop/src/renderer/src/features/graph/robots/RobotOrphans.tsx
apps/desktop/src/renderer/src/features/graph/robots/RobotNodeContent.tsx
apps/desktop/src/renderer/src/features/graph/robots/robots.css
apps/desktop/src/renderer/src/lib/api/workspace.ts
apps/desktop/src/renderer/src/lib/api/workspace.test.ts
apps/desktop/src/renderer/src/lib/api/resources.ts
apps/desktop/src/renderer/src/lib/api/resources.test.ts
```

Navigation directory includes its colocated tests. Keep old UUID coordinates; persist new defaults once; reuse complete cached snapshot and cap visible cards. Do not expand into snapshot/SSE refactors without measured evidence and explicit ownership reassignment. Remove only obsolete UI, never records that look like QA data.

### D1.list — context graph API and existing SOL note tool

```text
packages/api/src/solus_api/routers/solus_config.py
packages/api/src/solus_api/services/solus_config.py
packages/api/src/solus_api/services/solus_graph.py
packages/api/src/solus_api/agent/tools/solus_entry.py
packages/api/tests/test_solus_config.py
packages/api/tests/test_solus_graph.py
packages/api/tests/test_solus_entry.py
packages/api/tests/test_artifacts.py
packages/api/tests/test_artifact_retention.py
packages/api/tests/test_sol_red_team.py
```

Use `context_entity_id` only as a validated in-project reference on an existing bounded operation. Scope remains bound by Solus code; source-owned attributes and containment stay untouched. No new tool authorization model, artifact store, or alternate chat backend.

### D2.list — inspector and context actions

```text
apps/desktop/src/renderer/src/features/graph/GraphInspector.tsx
apps/desktop/src/renderer/src/features/graph/GraphInspector.test.tsx
apps/desktop/src/renderer/src/features/graph/InspectorSolComposer.tsx
apps/desktop/src/renderer/src/features/graph/InspectorSolComposer.test.tsx
apps/desktop/src/renderer/src/features/graph/WorkspaceScreen.tsx
apps/desktop/src/renderer/src/features/graph/WorkspaceScreen.test.tsx
apps/desktop/src/renderer/src/features/graph/SolusComposer.tsx
apps/desktop/src/renderer/src/features/graph/SolusNodeContent.tsx
apps/desktop/src/renderer/src/features/graph/useSolusNodes.tsx
apps/desktop/src/renderer/src/features/graph/useSolusNodes.test.tsx
apps/desktop/src/renderer/src/features/graph/useSolusConfig.ts
apps/desktop/src/renderer/src/features/graph/useSolusConfig.test.ts
apps/desktop/src/renderer/src/features/graph/solusActions.ts
apps/desktop/src/renderer/src/features/graph/robots/RobotNodeContent.tsx
apps/desktop/src/renderer/src/lib/api/resources.ts
apps/desktop/src/renderer/src/lib/api/resources.test.ts
```

`InspectorSolComposer` and test are new if a scoped wrapper is needed. Reuse the existing `features/sol/solChatStore.ts`, `useSolChat.ts`, `solApi.ts` and mentions support read-only; do not make incidental changes to the SOL feature being developed under occupied ticket 252. A submitted turn captures its entity/project/account rather than following later selection.

### E1.list — complete two-screen Hardware UI

```text
apps/desktop/src/renderer/src/features/graph/hardware/
apps/desktop/src/renderer/src/features/graph/robots/usePhysicalRobots.tsx
apps/desktop/src/renderer/src/features/graph/robots/usePhysicalRobots.test.tsx
apps/desktop/src/renderer/src/features/graph/robots/robotSession.ts
apps/desktop/src/renderer/src/features/graph/robots/RobotNodeContent.tsx
apps/desktop/src/renderer/src/features/graph/GraphInspector.tsx
apps/desktop/src/renderer/src/features/graph/GraphInspector.test.tsx
apps/desktop/src/renderer/src/features/graph/WorkspaceScreen.tsx
apps/desktop/src/renderer/src/features/graph/WorkspaceScreen.test.tsx
apps/desktop/src/renderer/src/features/graph/WorkspaceAdd.tsx
apps/desktop/src/renderer/src/features/graph/WorkspaceAdd.test.tsx
apps/desktop/src/renderer/src/features/graph/navigation/navigation.css
apps/desktop/src/renderer/src/lib/api/hardware.ts
apps/desktop/src/renderer/src/lib/api/hardware.test.ts
```

The directory owns all replacement/retirement of `HardwareAddPanel`, old Modals, `ProposalView`, constants and tests. It may add `HardwareChooseScreen.tsx`, `HardwareReviewScreen.tsx`, `useHardwareDiscovery.ts`, `hardwareDraft.ts` and colocated tests. Names are empty on every newly materialized row, even nested library/platform rows; suggested labels never initialize names. Existing entities preserve names and UUIDs. New standalone parts cannot create a fake robot. Integrate the working Sourced option as an information input without changing its separate sourcing service.

### E2.list — new black-box acceptance harness and recorded evidence

```text
tests/e2e/workspace_hardware_redesign.py
tests/e2e/fixtures/workspace_hardware_redesign/
docs/qa/PERFORMANCE_SOLUSDEV-256.md
docs/qa/HARDWARE_SOLUSDEV-256_live_results.md
docs/qa/SCREENSHOTS_SOLUSDEV-256/
```

These are new paths. The existing `tests/e2e` is pytest/httpx API E2E, not a desktop runner: use it for black-box API regressions and separately drive the actual Electron surface through a supported accessible app/debug interface. Do not label the Python HTTP test or a static renderer preview as desktop verification. Any maintained desktop harness/config addition gets an exact path and ownership amendment before implementation; no CI changes are in this assignment. Performance fixes return to their implementation owners, not an E2E catch-all ownership grant.

### Verification/document tasks — exact maps

Each of A4/B3/C3/D3/E3 owns its own completion/QA files and the explicitly associated governing docs below. These are orchestrator/doc-updater assignments. Review agents are read-only and own no implementation files; an empty manifest may contain `# Read-only review; no file edits`. Existing implementation owners are reactivated narrowly for findings.

```text
# A4.list
docs/qa/COMPLETION_SOLUSDEV-251.md
docs/qa/COWORK_QA_SOLUSDEV-251.md
docs/architecture/hardware-onboarding.md
docs/architecture/local-connections.md
docs/api/hardware.md
docs/api/workspace.md
docs/api/solus.md
docs/contracts/local-state.md
docs/schemas/hardware-config.md
docs/CODEMAPS/workspace.md
# B3.list
docs/qa/COMPLETION_SOLUSDEV-253.md
docs/qa/COWORK_QA_SOLUSDEV-253.md
docs/architecture/hardware-onboarding.md
docs/architecture/local-connections.md
docs/api/hardware.md
docs/wireflows/hardware-onboarding.md
# C3.list
docs/qa/COMPLETION_SOLUSDEV-254.md
docs/qa/COWORK_QA_SOLUSDEV-254.md
docs/architecture/workspace-navigation.md
docs/architecture/change-signal-spine.md
docs/api/workspace.md
docs/api/API.md
docs/wireflows/workspace.md
docs/CODEMAPS/workspace.md
# D3.list
docs/qa/COMPLETION_SOLUSDEV-255.md
docs/qa/COWORK_QA_SOLUSDEV-255.md
docs/api/solus.md
docs/wireflows/workspace.md
docs/architecture/workspace-navigation.md
docs/CODEMAPS/workspace.md
# E3.list
docs/qa/COMPLETION_SOLUSDEV-256.md
docs/qa/COWORK_QA_workspace_hardware_redesign.md
docs/architecture/workspace-navigation.md
docs/architecture/hardware-onboarding.md
docs/wireflows/workspace.md
docs/wireflows/hardware-onboarding.md
docs/api/workspace.md
docs/api/hardware.md
docs/api/solus.md
docs/CODEMAPS/workspace.md
```

Split that final block into five separate files at its labeled comments; do not grant all doc paths to every reviewer. Tier-1 design updates are written before the relevant implementation, then these tasks verify their currency. The orchestrator alone also owns serial regeneration of `packages/api/openapi.json` and `apps/desktop/src/renderer/src/lib/api/schema.ts` after each route change (A3 already lists them); add these two exact paths to the active integration/verification manifest at C3/D3/B3/E3 if generation changes them. Never run concurrent generations.

## 6. Test-first targets

For every implementation: write the cases below first in its owned tests, run them and record the expected failure, implement minimal behavior, then rerun and refactor. Tests derive from observable requirements; do not merely assert the newly chosen helper names. Existing tests named below are extended where useful; new files remain narrow. Root's “Full Test Coverage” requires coverage of all specified behavior/security cases, with the harness's 80% minimum as a floor, not a substitute.

| Task                 | First tests and required failures                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A0                   | No implementation tests: capture baseline spans and a read-only anomaly report; don't manufacture failures for reporting.                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| A1                   | `test_hardware_config.py`, new `test_hardware_config_migration.py`, `test_hardware_ownership.py`, `test_hardware_operations.py`, then existing router/attach/detect/library/physical-robot/resolver tests. Loose bracket/battery saves without robot/driver/calibration; all new names trimmed and required; pure GET does not create/recreate config; expected-version conflicts; duplicate first writes; operation replay across response loss; same key/different payload conflict; cross-user/project key isolation; saved node remains after failed connection.                                 |
| A1 migration         | Preserve all existing robot CONFIG entry IDs and all graph UUIDs; extract nested part config and remap provenance correctly; retain detached/deleted-robot parts; distinguish duplicate/conflicting copies; preserve invalid/conflicting evidence without making limits/calibration operational; redact raw legacy paths from transformed shared state/history; rerun is idempotent; wrong-project subjects/edges fail; unique active subject/config constraint after validated preflight; fail clearly on unrepresentable downgrade. Exercise real PostgreSQL constraints/locking, not only SQLite. |
| A1 ownership/runtime | Reassign/detach/remove robot without losing part entry ID, calibration, provenance, source ID/external_ref/canonical links/coordinates/provider containment; invalidate/disable stale controller bindings; imported entity configuration writes only manual CONFIG/references; ambiguous telemetry endpoint resolves to none/error; cache invalidation on binding change; connect assembled v2 config through existing drivers and unchanged telemetry packet.                                                                                                                                       |
| A2                   | New `hardwareLocalState.test.ts`, `hardwareSources.test.ts`: 0700/0600 and atomic writes; 256 KiB/16-account/256-map limits from shared contract; invalid/newer/corrupt handling; path traversal, symlink/canonical path changes and hostile IPC sender; unauthenticated project/account reuse; picker-only authority; no raw path leaks to shared payload; scope switch clears stale pending replies; content digest reflects selected bytes.                                                                                                                                                       |
| A3                   | New `test_hardware_local_sources.py` and typed client tests: authenticated project/account/source-ref lookup; absolute remote `repo_root` refused as file permission; wrong-account refs and changed digests fail/review; absent runner cannot read local files; API shape/If-Match/idempotency headers and legacy adapters; private hints never grant ambiguous reconnect.                                                                                                                                                                                                                          |
| A4                   | Run migration, Python/TS private-contract parity suites and A suites; fresh code/security/Python/TypeScript/database review on the same diff. No new mirror tests for reporting.                                                                                                                                                                                                                                                                                                                                                                                                                     |
| B1                   | New `lb_port_leases_test.py`, `lb_hotplug_test.py`, plus reconnect/serial/session tests: simultaneous probe/raw/session callers open a port at most once; active session remains undisturbed; release on cancel/failure/shutdown; factory open inside retry handling; finite overall probe deadline; old generation cannot reclaim a port; generic cross-project busy response; serial-less and duplicate-serial observations remain distinct; replug invalidates ephemeral selection.                                                                                                               |
| B2                   | New `test_hardware_evidence.py`, extend detect/repo-parser/LeRobot/three-machine tests: staged transport→board→protocol→platform evidence; generic bridge remains MCU-unknown; calibration unit ambiguity preserved; missing/digest-changed source prompts; matching old entity preserves all prior config; material revision changes require reviewed re-confirmation; unsupported protocol permits save; no “live” from a ping; channels only from actual capabilities; untrusted files/device text cannot alter tool/auth scope.                                                                  |
| B3                   | Run local runtime conformance, vendor ratchets, supported plugin fixtures, three-machine proof and typed errors. Record live passive checks distinctly from fixture-only transports.                                                                                                                                                                                                                                                                                                                                                                                                                 |
| C1                   | Extend connections/sources/Onshape/workspace-layout tests: account display name survives mapping/persistence/serialization; absent name gets honest fallback; equal display names never merge accounts; teammate attached-source groups visible without account catalogs; no additional provider read/scope; layouts reject fake UUIDs/stale versions/cross-project groups.                                                                                                                                                                                                                          |
| C2                   | `WorkspaceAdd.test.tsx`, `GraphNavigator.test.tsx`, `graphIndex.test.ts`, `useWorkspaceLayout.test.ts`, `workspaceFocus.test.ts`, `WorkspaceScreen.test.tsx`: complete labels under narrow/wide viewports; stable loading anchor; keyboard/focus/Escape/outside click; body drag vs click/double click; controls don't drag; keyboard move; normal wheel pans; explicit enter/back; reduced motion; no ownership API during drag; old positions survive refresh/import/reload; bounded cards and cross-links; real UUID focus despite account groups; retained-part reveal after reload.             |
| C3                   | Provider-call counters assert zero calls for selection/zoom/drag/reopened cached listing; measure screen interactions and frames on representative cached graphs. Verify concurrent layout conflict resolution against fresh teammate positions.                                                                                                                                                                                                                                                                                                                                                     |
| D1                   | Existing solus config/graph/entry tests first: in-project context edge, connector properties unchanged, no new context on failed upload, cross-project/deleted context 404, bounded entries/files, shared tool's never-raises and unknown-field rejection, artifact retention/deletion unaffected.                                                                                                                                                                                                                                                                                                   |
| D2                   | Inspector/composer tests: node click paints cached summary with zero model calls; explicit send uses the selected real entity UUID and existing project conversation; busy/budget/auth failures preserve draft; Guide/Expert; submitted reply stays with original entity after selection/account/project changes; Import/Ask SOL/Add note visible for supported nodes; retained part assignment available in inspector.                                                                                                                                                                              |
| D3                   | Existing SOL red-team and action-confirmation suites; verify no new system instructions derived from ingested note/device content, no secret/private-path context, no bypass of budgets or motion/destructive confirmation.                                                                                                                                                                                                                                                                                                                                                                          |
| E1                   | New choose/review/draft/discovery tests plus existing Hardware and Workspace tests: exactly two normal screens; detected/search/describe/import/retained/library inputs; every new name initially empty and enforced even on library-generated rows; existing names preserved; standalone passive entities; optional parent; one ambiguity at a time; draft survives hotplug/progress/back/error; stale requests after A→B→A discarded; save-only versus save-and-connect labels; failure retry targets saved IDs and cannot duplicate creation.                                                     |
| E2                   | New `tests/e2e/workspace_hardware_redesign.py`: HTTP black-box identity/config retention, idempotency, tenant/auth, saved-but-disconnected retry, source-safe context links. Separately exercise actual desktop flows and available arms with test data/config entered through normal user-facing workflows; record screenshots/traces/counts/spans without secrets/private paths.                                                                                                                                                                                                                   |
| E3                   | Integrated regression suite, migration head check, type/lint/build/coverage and fixed-diff reviews; rerun affected behavior after any correction, then final prescribed broad verification.                                                                                                                                                                                                                                                                                                                                                                                                          |

Use established commands and package environments: targeted `uv run pytest <owned test paths>` for Python; `pnpm exec vitest run <owned test paths>` for colocated TS tests; API export/typed client generation via existing `make gen-openapi`; desktop `pnpm --filter @solus/desktop typecheck` and build; repository lint/type/test commands and the installed `/quality-gate`, `/code-review`, `/test-coverage`, `/refactor-clean`, `/update-docs`, `/update-codemaps` workflows. Read their current command files before executing; do not edit the hooks or CI to make checks pass. The desktop CLAUDE documents a Vitest hook invocation quirk; report an actual recurrence rather than treating it as permission to bypass gates. A single Alembic head and PostgreSQL migration/constraint/race tests are required for A/C.

Measure before choosing optimizations. Record reference OS/CPU/GPU, viewport, graph entity/edge counts, visible-card count, build mode, sample count and p50/p95/max. Capture panel-open→paint, OS-enumeration→row, lease wait, probe stages, parse/cache stages, proposal reconciliation, confirmation verification, commit, connect→first actual packet, node-select→summary, frame durations while dragging, graph refresh. Acceptance targets: local feedback ≤100 ms; OS-enumeration→list ≤2 s; smooth dragging around 16.7 ms/frame on representative graphs. Keep naming/cancel/unrelated controls usable during work. Include 243+ graph entities, at most the documented visible-card bound, cached and cold conditions, and repeated imports. Unmeasured or failed targets are reported as such and corrected when the cause is in scope; no numerical result is assumed from passing unit tests.

## 7. Risks & flags

- **Approval status:** the design/tier-2/private-state changes and five-ticket split are already approved, and the numbering instruction resolves IDs. Do not repeat Phase 1. The root orchestrator owns the exact approved protected patch and its parity tests; workers consume it. Any genuinely additional frozen-contract/ADR change needs a concrete proposal before edits, not a hidden extension of the approval.
- **API design currency:** the approved creation/config/parent/unassigned, reviewed proposal/session and optional `.solus` context surfaces are amendments to existing route plans. The orchestrator records exact methods, fields, versions, statuses and limits before their implementation. No undocumented route or separate orchestration/backend is to be built. The exact idempotency persistence mechanism must be documented in A's schema/API design before A1 writes it; observed billing-only storage is unsuitable for hardware operations.
- **Migration safety:** existing data may contain duplicate configs, embedded copies after ownership changes, orphaned/deleted robot references and private paths. Preflight reports evidence and fails closed on unresolvable operations; it does not pick calibration winners, delete user data, run arbitrary legacy files, or pretend v2 standalone state downgrades losslessly. Migrations are tested on copied/fixture datasets before application to the user's project.
- **Ownership and source identity:** configuration is subject-owned; assignment is a separate manual edge. Provider external_ref, source identity, canonical links and containment survive binding and moves. Imported nodes cannot gain convenience attrs through manual APIs. Resolver ambiguity must not silently select the first row.
- **Local machine trust:** MAIN's authenticated sender/project/account and picker authority, file modes/size/atomic writes, canonical path checks, digest revalidation and cloud runner-absence behavior are dedicated security-review surfaces. Private path provenance is removed from shared configuration and model input; a port hint is not durable identity or consent. The local file has no credentials, ownership facts, server settings or calibration values.
- **Hardware race/cancellation:** HTTP cancellation does not itself stop a thread. Overall probe timeout, cooperative close/release and a single machine-wide lease must cover all existing open paths, including raw serial and reconnect, with no busy-owner identity leak to another project. Verify this before introducing hotplug-driven work.
- **Readiness and safety:** ping/recognition/commit/session-open/actual packets are independent states. Saving unsupported hardware succeeds. Explicit connection retry uses the saved config; no duplicate creation. No simulation proof of physical safety, inferred missing capabilities, motion/flashing/deployment, driver generation, per-device containers, OpenUSD or new simulator enters this scope.
- **Account and renderer identity:** account display strings are untrusted presentation data, never grouping IDs. Pending work is permanently invalidated on intervening account/project changes. Real graph IDs and truthful Focus ancestry remain intact; account groups are not graph entities. No passive UI action spends provider quota or invokes a model.
- **SOL and document input:** notes/artifacts/device strings and model output remain untrusted data. Test prompt boundaries, rendering sanitization, graph authorization, existing budgets, concurrent-turn refusal and concrete action confirmations. D must reuse the existing SOL seam while leaving unrelated ticket 252 work untouched.
- **Tooling limits:** H12's lowercase runtime path and union behavior are observed and called out above. No hook modifications. The requested Ponytail check may be unavailable in this tool environment; the orchestrator must check available capabilities and record any actual gap, while still completing the required fresh code/refactor review. Do not install an unrequested unrelated plugin as a substitute or claim an unavailable review ran.
- **Live application access:** a static renderer and component tests do not satisfy Electron QA. Establish the real supported desktop control/debug surface; complete all independent code/tests/fixtures if physical interaction or native access requires user involvement, then ask only for the concrete missing action. Do not weaken Electron security settings to obtain test access.
- **Physical test matrix:** available hardware is the LeRobot arms; ELEGOO is unavailable. Before adding context, record missing-information prompts. Add evidence-backed identity/bus/joint/calibration information through normal project `.solus` UI, then reopen and repeat; preserve both arms' actual entity/config IDs, demonstrate distinct matching, correct packet-part mapping and units. Unplug/replug/port swap is live only if actually performed. No individual arm identity/address/topology/calibration is hardcoded in app or shared UI. Fixture-test unavailable transports/scenarios and keep them separate from live results.
- **Completion:** every ticket gets a self-contained Cowork QA with setup, numbered steps/expected results, pass/fail checks, failures, permissions, and cross-feature effects. Final E report names governing docs, local branches/commits, measured performance, exact live hardware actions, fixture results, remaining unverified items and decisions under delegated judgment. Review findings are fixed before handoff; no claim of full completion while mandatory live/application verification remains undone.
