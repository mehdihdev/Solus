# Workspace navigation

Updated for SOLUSDEV-242 Phases 1–4. Authority: `docs/architecture/workspace-navigation.md`.

| Boundary         | Implementation                                                 | Responsibility                                                   |
| ---------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| Screen           | `features/graph/WorkspaceScreen.tsx`                           | Graph, layout and shared focus integration                       |
| Snapshot         | `features/graph/useWorkspaceGraph.ts`                          | Complete entities/relations; project version/TTL; auth isolation |
| Navigator        | `features/graph/navigation/GraphNavigator.tsx`                 | Bounded cards, breadcrumbs, paging and cross-links               |
| Type declaration | `features/graph/navigation/nodeTypes.ts`                       | Registry declares containment children                           |
| Index            | `features/graph/navigation/graphIndex.ts`                      | Deterministic forest; cycles/multiple parents; projected links   |
| Geometry         | `features/graph/navigation/layout.ts`                          | Visible-level positions and stable origin                        |
| Interaction      | `features/graph/navigation/useGraphNavigation.ts`              | Wheel, zoom, paths and draft drag coordinates                    |
| Persistence      | `features/graph/useWorkspaceLayout.ts`                         | Captured-identity write queue, pruning, conflict retry           |
| Focus            | `features/workspace/focusStore.ts`, `useSharedFocus.ts`        | Real entity selection and ancestry to Live Bench/widgets         |
| HTTP client      | `lib/api/workspace.ts`                                         | Relation pagination and typed layout API                         |
| API              | `routers/workspace_layout.py` → `services/workspace_layout.py` | ProjectCtx, validation, locking, metadata event                  |
| Storage          | `models.WorkspaceLayout`                                       | Project FK, JSONB positions, optimistic version                  |

| `.solus` UI | `features/graph/useSolusNodes.tsx`, `SolusNodeContent.tsx`, `SolusComposer.tsx` | Real-node menus, inline editing, concrete deletion confirmation |
| `.solus` actions | `features/graph/solusActions.ts`, `workspaceFocus.ts` | Existing upload/SOL/text flows, guarded refresh and focus invalidation |
| `.solus` graph | `services/solus_graph.py` → `services/solus_config.py` | Project lock, six baseline nodes, entry identities, preserved artifact references |

Renderer paths are relative to `apps/desktop/src/renderer/src`; Python paths are
relative to `packages/api/src/solus_api`. Migration `a3f242b9c610` follows `2cd33377eeb0`.
Migration `b6f242d8e731` follows `a3f242b9c610` and backfills `.solus` containment.
Migration `c7f242e9a842` follows `b6f242d8e731` and wraps legacy Onshape graph roots locally.
No provider or sync dependency exists in the navigator. Physical robots follow in Phase 4.

| Service picker | `features/graph/WorkspaceAdd.tsx`, `ServiceAccountPanel.tsx` | Cached accounts/document choices and explicit listing refresh |
| Catalog | `features/graph/serviceCatalog.ts`, `useServiceCatalog.ts` | Coalesced I1 reads retained per signed-in identity |
| Attachment | `features/graph/serviceAttachments.ts`, `useServiceAttachments.ts` | Exact project/account binding, first job, zero-request reselection |
| Session boundary | `features/graph/workspaceSession.ts` | Permanent invalidation across intervening account/project switches |
| Live graph | `lib/api/projectEvents.ts`, `features/graph/useWorkspaceEvents.ts` | Authenticated SSE, scope validation, reconnect/catch-up |
| Document graph | `connectors/document_graph.py`, `connectors/onshape.py` | Stable document wrappers over preserved assembly/part trees |

| Physical Robot UI | `features/graph/robots/usePhysicalRobots.tsx`, `RobotNodeContent.tsx` | Manual creation, inline rename, confirmed removal |
| Robot session | `features/graph/robots/robotSession.ts`, `RobotOrphans.tsx` | Guarded versioned writes and persistent paginated part reveal |
| Robot client | `lib/api/physicalRobots.ts`, `client.ts` | Typed narrow entity routes and If-Match version header |
| Robot service | `services/physical_robots.py`, `routers/entities.py` | Atomic independent categories, R2 creation hook, explicit ownership retention |
| Graph validator | `routers/projects.py`, `features/graph/graphCache.ts` | Graph modification timestamp catches manual renames |
| I1 | `routers/connections.py`, `services/connections.py`, `connectors/integration_cache.py` | Cache-only miss contract, exact account reuse, shared version payloads |
| Sync gates | `connectors/runtime.py`, `worker.py`, `httpcache.py` | Fail-closed probes, owned renewable flights and bounded accepted jobs |
