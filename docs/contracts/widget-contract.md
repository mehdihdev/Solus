# Widget Contract — the workspace seam (SOLUS-WS-00, extracted from WS-01/WS-03)

**Status:** Ratified contract (ADR-032 landing, 2026-08-01) — and IMPLEMENTED at
`apps/desktop/src/renderer/src/features/workspace/widget.contract.ts` (`WIDGET_CONTRACT_VERSION = 1`).
**Authority:** CLAUDE.md §3 (wireflows govern UI structure — **none exist for the workspace; see
§7**) · §7 (the model proposes, Solus code decides — applied here to the UI) · §8 (typed API client
only; Zustand for cross-component state) · ADR-008 (Electron/React/TS/Zustand) · ADR-025
(project-as-workspace) · `apps/desktop/CLAUDE.md` (feature-panel layout, store conventions).
**Consumers:** WS-01 shared-focus engine (implemented) · WS-03 widget canvas · WS-02 focus bar +
traversal breadcrumb · WS-04 saved layouts + `arrange_workspace` · every future lens (schematic,
CAD, telemetry, Impact).

---

## 1. Why this contract exists separately

WS-01 (the focus engine) listed WS-03 (the canvas) as a dependency, and WS-03 listed WS-01. Neither
could start — the same deadlock shape as BRG-01/BRG-02.

The cycle was never real. What each side actually needed from the other was **the contract between
them**, not the other's implementation. Extracting it into one file dissolves the dependency: WS-01
builds against this, WS-03 builds against this, and neither builds against the other.

**Proposed as its own ticket (WS-00)** so the dependency graph in Jira matches reality.

## 2. The model: a widget is a lens on the shared focus

There is exactly one focused entity in the workspace. Every mounted widget shows _its_ view of that
entity. Selecting a part in any widget re-scopes all of them — **selection is the query**. This is
the graph being used, rather than a node-link diagram being stared at.

A widget therefore has a deliberately tiny surface: it **receives** the focus, and it **emits**
requests. That is all.

## 3. What a widget receives — `WidgetFocus`

| field           | type                                        | meaning                                                                      |
| --------------- | ------------------------------------------- | ---------------------------------------------------------------------------- |
| `status`        | `'idle' \| 'loading' \| 'ready' \| 'error'` | Lifecycle of the shared focus.                                               |
| `focusedEntity` | `Entity \| null`                            | The selected entity, resolved from the neighbourhood — not a second request. |
| `neighborhood`  | `Neighborhood \| null`                      | The bounded subgraph around it, fetched **once** and shared.                 |
| `error`         | `string \| null`                            | Set when `status === 'error'`. Solus-authored text, safe to render.          |

`Entity` and `Neighborhood` come from the typed API client (`lib/api/resources.ts`) — the same types
`/entities` already returns, so the frontend has **one** entity type rather than a widget-specific
copy that could drift from the backend.

Two obligations on the widget:

- **Never fetch your own scope.** The host fetches once per selection; N mounted lenses must not
  become N requests. A widget that fetches is a widget that can disagree with the others.
- **Surface `neighborhood.truncated`.** The server caps results; a silently capped neighbourhood
  reads as the whole picture.

## 4. What a widget emits — `WidgetActions`

| action                      | meaning                                                                           |
| --------------------------- | --------------------------------------------------------------------------------- |
| `refocus(entityId)`         | Move the shared focus. Every other widget re-scopes; the canvas does not remount. |
| `requestSolAction(request)` | Ask SOL to act. `{kind, entityId?, detail?}`.                                     |

Deliberately **two verbs**. A widget cannot mutate the graph, cannot fetch its own scope, and cannot
reach another widget — each of those would be a way for one lens to desynchronise the rest.

**`requestSolAction` proposes; the host decides — and enforces.** This mirrors CLAUDE.md §7's rule
for the model layer ("the model requests, Solus code decides") applied to the UI: a widget never
invokes a tool directly, and `SolActionRequest.detail` is untrusted text that reaches a model as
data, never as instructions. Until WS-04 registers `arrange_workspace`, an unhandled request is a
deliberate no-op rather than a fake success.

`kind` is a **closed union**, `SOL_ACTION_KINDS = ['explain' | 'diagnose' | 'arrange_workspace']`,
and `WidgetHost` validates against it **at runtime** — the TypeScript union is erased, and once
WS-04 lets SOL arrange the workspace a widget's request becomes model-influenced input, which §7
requires be checked against an action set fixed in Solus code beforehand. An unrecognised `kind` is
dropped, not forwarded. Adding a member is a contract change, which is exactly the friction the
rule intends.

## 5. Registering a widget — `WidgetDescriptor`

```ts
interface WidgetDescriptor {
  id: string; // stable; persisted in saved layouts (WS-04)
  title: string;
  Component: ComponentType<WidgetProps>;
}
```

`id` is persisted in a user's saved layout, so renaming one orphans that layout. Treat it as data,
not as a label.

**Adding a lens is: implement `WidgetProps`, export a descriptor.** No canvas change, no new store,
no bespoke wiring — which is the acceptance criterion WS-03 is measured against.

## 6. Versioning

`WIDGET_CONTRACT_VERSION = 1`. Adding an optional field is compatible. Removing a field, retyping
one, or adding a required one is breaking: bump the version and update every widget in the same MR.
There is no runtime negotiation — all widgets ship in one binary.

## 7. Governing-doc gap (flagged, not improvised around)

`docs/wireflows/` is **empty** (`.gitkeep` only), and `docs/architecture/` likewise. CLAUDE.md §136
says an absent wireflow means the design phase is incomplete and should be flagged rather than
invented around. This contract therefore fixes only the **seam** — data in, requests out — and takes
no position on layout, visual design, or which lenses exist. Those are wireflow decisions, and when
wireflows land they win (CLAUDE.md §3) and this document is reconciled in the same MR.

The closest existing plan of record is the restored `docs/api/API.md` §5 frontend route map, which
predates the workspace shell and is itself marked as intent rather than structure.

## 8. Functional vs. future

| in this contract                                    | deferred, and to where                                            |
| --------------------------------------------------- | ----------------------------------------------------------------- |
| What a widget receives and emits                    | —                                                                 |
| Registration descriptor                             | —                                                                 |
| Host wiring (`WidgetHost`) + two reference widgets  | —                                                                 |
| Layout, resize, drag, docking                       | **WS-03** — the canvas                                            |
| Saved named layouts, `arrange_workspace` tool       | **WS-04**                                                         |
| Focus bar, traversal breadcrumb, back/forward       | **WS-02**                                                         |
| Multi-select / comparison focus                     | Not designed — one focused entity by construction today           |
| Per-widget scoped filters (`entity_types` per lens) | Possible via the existing route params; no contract change needed |

## 9. Cross-references

`docs/api/API.md` §2.4 + `docs/api/API-implementation.md` §12 (`GET /projects/{id}/graph`, the
focus-scope read) · `docs/contracts/agent-tool.md` (W0-04 — where `requestSolAction` eventually
lands) · `docs/contracts/sol-interface.md` (W0-07 `GraphScope`/`GraphContext`, the same traversal
the focus engine uses) · `docs/qa/COMPLETION_SOLUSDEV-191-ws01-focus.md`.
