# Architecture — Workspace navigation, Integrations and inspector

**Last updated:** 2026-09-11. **Status:** integrated SOLUSDEV-250/260 navigation, retaining
explicitly identified 254/255/256 follow-up design, extending
W1–W4 (SOLUSDEV-240/242). Governing decisions: ADR-001/005/008/025/027/030/034.
[Wireflow](../wireflows/workspace.md), [workspace routes](../api/workspace.md),
[.solus routes](../api/solus.md), [hardware ownership](hardware-onboarding.md),
[Focus contract](../contracts/focus.md), [change signals](change-signal-spine.md).
No graph domain or Focus contract changes. Completion reports distinguish the approved target
from implemented behavior and measured results.

```mermaid
flowchart LR
  Graph[Authorized project graph and source metadata] --> Index[Real containment and presentation index]
  Accounts[Owner-only cached integration catalog] --> Add[Centered Add modal]
  Add --> Attach[Existing exact source attachment]
  Attach --> Graph
  Index --> Groups[Account boundaries and native document hierarchy]
  Groups --> Canvas[Bounded spatial canvas]
  Canvas --> Layout[Versioned UUID positions and separate group placement]
  Canvas --> Focus[Real entity Focus]
  Focus --> Inspector[Cached summary then relationships and evidence]
  Inspector --> Action[Explicit Ask SOL / note / import]
  Action --> Existing[Existing project conversation and .solus entry services]
```

## Real graph identity and presentation

`contains` is parent→child, `part_of` child→parent; other edges remain cross-links. A
deterministic presentation forest resolves multiple parents/cycles without mutating the graph.
Additional links retain their real endpoints and counts. Actual selection always addresses a
real UUID with truthful graph ancestry, independently of the two-hop focus query cap.

Integrations use presentation account groups keyed by provider plus proven provider account
identity. If identity is unavailable, use distinct existing connection/source fallbacks until
proven. Never key groups by display name or invent EntityRef/graph UUIDs for headers. Project
source metadata supplies teammates' attached-source groups; the owner-only connection catalog
supplies Add choices. It must not expose another account's private document/repository listing.

Display provider logo and readable account name, then real imported document/repository roots
and their native hierarchy. Preserve `AccountInfo.name` separately from login/external ID when
already supplied by an authorized response, and mirror it into project source display metadata.
For Onshape, prefer the authorized session display name, then account email; if neither is
available use an honest provider account label, never the opaque provider id as the username. Do not broaden OAuth permissions to obtain display data.
Onshape preserves document→assembly→part; Git preserves repository→directory→file. Exact
account/document/repository/branch matching prevents duplicate imports. Unbound sources remain
separate until identity is proven.

`.solus` remains the real top-level configuration node with seven section entities (and subsection nodes, SOLUSDEV-320) and real
entry/artifact graph identities. Text remains authoritative in solus_entries. Robots remain
independent manual roots with existing category nodes, but empty categories may collapse/hide
in presentation. Parts may remain unassigned and independently configured. Retained parts are
reachable through Hardware search and the inspector even when provider containment supplies
their normal presentation parent. Group membership and canvas position never assign hardware.

## Edges with meaning (SOLUSDEV-320)

Every projected link is labelled by its dominant `relation_type` (never "N links"); the bundle
between two cards expands on click to one path per relation. Visual weight follows the
`RelationClass` from `@solus/shared-types` `relations.ts` through CSS variables on
`.graph-cross-edge`: structure thin and quiet, dependency loud, identity collapsed as today,
outcome dotted, candidates (`origin = inferred`, `confidence < 0.8`) dashed. Hovering shows a
sentence built from the type, the two names and the evidence refs (`edgeSentence.ts`, no model
call). Clicking a path opens `EdgePanel` in the sidebar: type, direction, confidence, origin,
every evidence item with its ref, created by and when, matrix cell, `attrs.checker_results` when
present, and Confirm / Decline on candidates (`POST /edges/{id}/confirm|decline`). Selection
state for an edge is local to the Workspace screen, like account anchors; synthetic projection ids
never open the panel. Cards carry a finding badge (highest open severity + count from
`GET /findings?status=open`, refetched on `graph.changed` and `finding.*`). The viewport context
menu offers **Re-layout**, which clears the current level's saved positions through the versioned
`PUT /workspace-layout` and lets default placement run again. Wheel zoom, free drag, the 24-card
bound, `.solus` centred, account anchors and reduced motion are unchanged. Route plan:
`docs/api/relations.md`, `docs/api/findings.md`.

## Canvas interaction and persistence

Design template (2026-10-24): the top-left toolbar is the accent Add button, a breadcrumb pill
(`GraphBreadcrumb`: the navigator's trail, a back arrow when deeper) and a mono level stat drawn
from the navigator's own counts; Help stays top-right; a zoom pill (`−` / `NN%` reset / `+` /
`Fit`) sits bottom-right and is camera-only presentation zoom (`stepGraphZoom`, 50–200 %,
never a coordinate write). Escape is owned at the window by the navigator: dialogs and editors
win (they `preventDefault` or sit inside `EDITABLE`, which includes the toolbar corner the Add
modal renders from), then the screen may consume it to close the side panel, then the level goes
up. Save/conflict/error feedback stays in the discrete status row below the canvas.

The incoming 250 navigator uses hover + wheel inward to enter the hovered card's immediate
children and outward to go up one level. Double-click, keyboard, the breadcrumb pill (back arrow
and crumbs) and Help → Project overview are equivalent hierarchy controls; leaves select without entering an empty level.
Click selects; body drag excludes inputs/buttons and crosses a movement threshold. Coordinates
remain transformed correctly and keyboard movement/reduced motion remain supported. This is the
current integrated interaction; the earlier plain-wheel-pan redesign is not claimed implemented.

Preserve UUID-keyed saved coordinates across reload/import/refresh. Generate initial positions
once and persist them: subsequent imports place new nodes without rearranging existing defaults.
Spatial account/group boundaries expose useful populated assemblies and individual parts.
Current account anchors are client-only presentation nodes (`account:<key>`, integration domain
sentinel), grouped by proven connection identity with source fallback. They never enter shared
Focus or `PUT /workspace-layout`. Under the September 15 UI brief, their positions persist in
separate account/project-scoped local presentation preferences, with finite bounded coordinates.
Real entity UUID coordinates remain project-shared. Shared typed group placement remains later
work; local preferences never manufacture graph UUIDs or enter shared Focus.
Explicit arrange/reset is the only automatic layout rewrite requested by a user.

Initial placement (2026-10-24) fills rows of three below the current parent — centre, right,
left, then the next row — with collision avoidance against saved points; a cell past the
coordinate boundary mirrors to the other side. Existing saved points are never recomputed. The
level frame hugs the cards (`levelBounds` pads their bounding box; it no longer centres the
parent's point, which left an empty half above the first row). The level also draws containment
structure (`StructureLine`s: inside a level one stem from the frame's top edge into a bus above
the first row with a drop per card — there is no parent chip, the breadcrumb owns "up"; at the
root the `.solus` hub → other roots) as unselectable dashed paths behind the cards; cards are
`user-select: none` (editors inside keep text selection) so a press-and-drag never highlights
text; the cross-link legend
and endpoint list below the canvas were removed, and paging renders only past 24 cards. Dragging
the viewport background pans it (`useDragPan`, pointer capture; cards and controls excluded). Visible projected edges aggregate real relationships and counts, draw
curved paths with midpoint labels, and distinguish cross-domain links from quiet containment.
Pending suggestions use existing project-authorized proposal evidence and explicit decisions;
rendering them never generates or accepts links.

Small graph overviews may fit the visible card bounds using presentation zoom without changing
world coordinates; explicit `−`/`+` steps clamp 50–200 % around the viewport centre and never
persist coordinates. Drag deltas are converted back into world units before persistence. Framing
is recomputed for viewport or visible membership changes, never to rearrange a dragged node.
Cards are 300×184 (`layout.ts`); saved points are centres, so the size change migrates nothing.

Keep the documented 24-card visible bound and explicit additional-child navigation until measured
rendering evidence justifies a separately documented bound. Project snapshots may be complete;
render/layout work is bounded to visible content, with projected cross-links preserving actual
endpoints. No force solver runs across hidden entities. Camera state is presentation state,
not provider or ownership data.

Layout saves remain project-shared and versioned. Preserve the latest pending moved-node set
while a write is in flight. On conflict, load the newest layout and offer explicit resolution;
retry applies only the user's changed positions without erasing teammate coordinates. Unknown
fields, cross-project IDs/group keys, nonfinite or oversized coordinates are rejected.

## Cache, imports and live refresh

Reuse the current cached I1 listing. First expansion is cache-only; Load documents and Refresh
are explicit provider operations. Refresh accounts discovers new Home connections. Reopening a
cached catalog, selecting nodes, entering levels, dragging, zooming or refreshing graph data
performs no provider call. Confirming picked documents attaches/syncs each in order through the
same `ServiceProject.select` (it serialises on `busyId`); reselecting an attached document focuses
its existing root. Errors remain inline with Integrations recovery guidance.

The existing authenticated project event stream invalidates snapshots on committed graph hints.
Initial readiness validates project version to close the subscribe/snapshot race; reconnect
refreshes Solus data only. A committed graph-change hint always invalidates the display, even
when `MAX(updated_at)` and counts compare equal: timestamps are not commit-order revisions.
Hardware full-list frames are local-only. Their authoritative arrival supersedes any pending
GET seed; neither old stream nor old seed may repopulate another account/project scope. Permission failures stop retries. Every async operation is scoped by a
monotonically increasing account/project generation; old results cannot revive after A→B→A.
The existing local provenance migration for Onshape document wrappers preserves assembly/part
IDs and makes no provider call. Manual robot edits publish graph hints after commit.

## Sidebar and explicit SOL actions

`NodeSidebar` mounts only for a selection (entity, account anchor or edge) and shares one chrome
(`sidebar/PanelChrome.tsx`: domain dot, `panelLabel`, ✕, title, real facts; footer strip).
Robot/category routes to the robot sidebar; `.solus` root/section/entry routes to its sidebar
(now with the Add / Edit · Upload · Ask SOL footer); account anchors use local account details;
other real entities show `ConnectionsPanel` — the cached neighbourhood's edges touching the node
as cards (`edgeSentence`, status pill from open findings on either endpoint) — instead of the
reference widgets, which remain the widget-contract fixtures. `focusStore.clearFocus` deselects
without dropping the cache. Per-robot detail refresh follows invalidation,
not a graph refetch for every click. Connection metadata renders connecting/connected/failed/
disconnected separately from actual packet reception. Serial-less identity copy appears here
as well as on the device card. Import/note expansion for every arbitrary node remains follow-up
work where no existing handler provides it.

Render selected local/cached summary promptly. Load relationships, evidence and connection details
progressively with honest loading/failure states. All supported nodes expose visible Import files,
Ask SOL and Add note actions in addition to relevant type-specific controls. A retained part can
be assigned/reassigned explicitly through the versioned ownership API.

Selection makes no model call. Explicit Ask SOL pins the real selected node to the project's active
chat (`features/sol/pinnedContextStore.ts`, localStorage, cleared when the account ends) and opens
the SOL page with a seeded draft; the SOL window keeps `openSolSubject`. Submission carries the
UUID in `MessageCreate.pins` (the chat's pinned nodes, capped at 8; typed `@`-mentions stay in
`mentions`), uses the current project conversation and consumes Guide/Expert mode,
action mode, budget admission and confirmation infrastructure. Bind each submitted turn to its
submitted entity, even if selection changes; stale account/project results are discarded. Do
not create a fresh chat for every click or invent a parallel agent service.

Notes/imports use existing project `.solus` sections, entry rows and artifact storage. A validated
optional context entity adds a manual `references` edge to the new entry graph node. It does not
edit source-owned content. Section/entry handlers, file/text limits, retention and deletion remain
shared. A failed upload/entry write creates no context edge. All retrieved content stays untrusted
model data and cannot change tool/auth scope.

## Verification

Use ProjectCtx/member writes; validate project-scoped IDs, versions and manual-edge permissions.
Required regression cases include account identity/fallback and teammate visibility, cached
provider-call counts, focus correctness, body drag versus controls, accessible responsive Add,
persisted positions after repeated imports, concurrent layout changes, retained-part reveal,
context isolation and no model call on selection. Preserve SOL budgets/refusal/confirmation tests.

Measure actual Electron panel→paint, select→summary, drag frame durations and graph refresh on a
representative 243+ entity graph with recorded machine/viewport/build/card counts and p50/p95/max.
Targets are ≤100 ms local feedback and roughly 16.7 ms drag frames, not assumed results. Record
actual desktop runs separately from component/API fixtures and fix review findings before handoff.

## Performance evidence

Confirmations use per-attempt marks rather than global marks that collide across devices.
Repeated device appearances begin new receipt-to-card spans. These spans start at browser
receipt, not physical plug-in; OS detection latency is measured separately. Target confirm
response-to-node well under 500 ms, sidebar feedback under 100 ms, and bounded drag/render work.
Targets and unit fixtures are not claims of measured native performance.
