# Wireflow — Workspace (SOLUSDEV-250/260 integration)

Authority: the approved combined Workspace request (SOLUSDEV-242); the design spec cited
previously (`docs/design/screens/SPEC.md`) does not exist in the repository.
Architecture: `docs/architecture/workspace-navigation.md`; routes:
`docs/api/workspace.md`, `docs/api/solus.md`, API.md §2.5.
This reconciles the incoming navigator/sidebar flow with independent hardware configuration
and the current SOL window. Completion evidence is recorded separately from this wireflow.

```
| rail | [Add]                    [parent chip]            [?] | sidebar   |
|      |                                                       |           |
|      |         typed node cards and distinct cross-links      | robot:    |
|      |                    .solus (center)                     |  rename · |
|      |                                                       |  parts ·  |
|      |                                                       |  connect ·|
|      |                                                       |  delete   |
|      | real graph counts · saving status  Previous / Next     | .solus:   |
|      |                                                       |  actions  |
|      |                                                       | entity:   |
|      |                                                       |  focus ·  |
|      |                                                       |  neighbors|
```

Add is a top-left corner button over the canvas; Help `?` (top-right) opens a small
popover with the navigation instructions, the current trail and **Project overview**;
the parent chip on stage is the up affordance. The sidebar (formerly "inspector") shows,
by selected type: physical robot — rename, parts by category, connection, pending
suggestions, unassigned parts, delete; `.solus` root/section/entry — sections, the three
actions, composer, edit/delete; any other entity — focus summary and neighbors.

## Navigator

A new project's only top-level node is `.solus`, centered. The Add button remains
available. No empty-state overlay covers it and no `.solus` left panel remains.
Connected documents cluster under their account anchor (provider logo + readable account identity); zooming
into the anchor shows that account's documents, and its sidebar lists them (select to
reveal) with "Add another" opening Add › Integrations. Manual robots appear around `.solus`.
New nodes pack beside their parent. No opaque id is shown as an account username. Real cards are draggable;
their positions are shared by the project and remain after reload. Client-only account anchor
positions persist locally per account/project and are never sent as graph UUIDs to layout or shared Focus. Saving/error/conflict
status is visible. Retry after a conflict saves only the user's moved nodes onto
the latest layout; it does not discard teammate positions silently.

Hover a card and scroll inward to reveal its immediate children with a transition
from that card. Scroll outward goes up one level. Double-click, explicit enter/back
controls, keyboard, the parent chip and Help › Project overview provide equivalent
navigation. Clicking any
entity updates the shared focus, including Live Bench. Leaves select without
zooming. Zoom never triggers source synchronization. Reduced-motion settings are
respected. A maximum of 24 cards render at once; explicit page controls reveal
additional siblings. Cross-domain links use distinct dashed styling, projected
onto visible ancestor cards; outside-level connections remain discoverable.

## `.solus`

### September 15 graph presentation amendment

The UI brief governs card presentation: rounded domain-bordered cards on a dark dot-grid,
monospaced names, actual type labels and metadata, and two-column child previews with actual
descendant counts. Unbound/proposal states use dashed borders only when supported by evidence.
Default placement is deterministic organic packing with non-aligned offsets, preserving every
saved point. Curved links display actual aggregated relationship counts at their midpoint;
cross-domain links are accented and dashed. Real pending proposals float beside their candidate
and expose evidence plus existing accept/decline controls. No fabricated proposals or metadata.

Enter `.solus` to see five section nodes: Hardware configs, Project details,
Error logging, Documentation, Code environment. Right-click any section gives
exactly **Import files…**, **Ask SOL to find…**, **Type it**. Reuse the W1 action
handlers and validation. Enter a section to see imported artifact cards and
text/SOL/error entries. Error entries can be edited in their card.

Import uses the existing 8 MiB upload boundary, then files the artifact. Typed
text uses the existing 4000-character limit. Text and SOL entry editing updates
the existing entry. Entry deletion uses the existing concrete confirmation, naming the file/note and its graph effects;
failures remain visible and never create a success card. Ask SOL remains disabled
while the project already has a streaming turn and reports honestly if no result
was filed. Failed edits keep their drafts. Account/project switches close editors and menus.
Graph mutations invalidate cached neighborhoods, refresh a surviving selection, and clear a
deleted selection. No automatic error-filing capability is implied.

## Add

Top-left **Add** opens a panel with **Integrations** and **Hardware** tabs.
**Hardware** is three sections in reading order — Devices found · Search · Describe
something new — then a collapsed **Unassigned parts** disclosure; no card grid,
preserving file/connector parts and the private-source subsection (`hardware-onboarding.md`). Offline it shows one
honest line and disables every control.
Integrations lists the accounts connected in Home and cached document/repo
choices. Reopening a dropdown reuses its loaded listing. Missing cached data is
an honest empty state with an explicit refresh action; opening the panel itself
never spends provider quota. Selecting a new document creates a project node and
starts its first sync. Re-selecting an existing node only focuses it. A second
Onshape document or Git repository creates a second root of that type.

Onshape: document → assemblies → parts. Git: repository → directories → files.
Loading/sync failures are shown on the selected source; unrelated nodes remain
usable. No provider call occurs on graph selection, zoom or layout changes.

## Physical Robot

A robot comes to exist three ways, all in Add › Hardware (`hardware-onboarding.md`): a
detected device's one-question card (Add saves it and schedules optional connection), a library
platform (Search › Add as new robot), or explicit robot creation elsewhere in the workspace.
**Describe something new** creates a part, including an unassigned part when no robot exists.
A name saves context; connection and actual
streaming require separate verified configuration and packet evidence. Standalone parts are
supported by the v2 API without requiring robot creation.
Detected devices not yet bound also dock as **pending cards at the canvas edge**, the
same cards Add › Hardware › Devices found shows, so a device plugged in mid-session is
visible without opening Add; adding or dismissing one clears it in both places.
Supplier results (STORE ST5, `sourcing.md`) appear inline under the same Search input.
An explicit metered supplier search uses the existing engine; typing alone never spends credits.
The existing supplier selection endpoint creates a planned part. Details expand inline and no
library, supplier or preview modal remains in Hardware. Existing BOM sourcing is independent.
These controls are disabled offline. A robot's name is editable inline in the robot's sidebar, where rename, delete,
unassigned parts, pending suggestions and connection status live. Multiple robots coexist
with independent names and containment.
Enter a robot to see Sensors, Actuators / motors, Controllers, End effectors,
Power, Structure, Wiring; enter a category to see its parts. Empty categories
show an honest empty state. Every configured subject owns an independent v2 CONFIG; robot
and controller connection fields refer to current part configs through the runtime adapter.
Absent config remains absent until an explicit save; selecting it never creates database rows.

Deleting a robot shows an inline two-step confirmation in the sidebar and explains that
its parts are retained. After confirmation the parts remain reachable as unassigned: Add › Hardware ›
**Unassigned parts** (collapsed; nothing is read until opened) uses one unified paginated
query for retained, manual and connector parts, each with Part of ▾ + Category ▾ + Add. No
second orphan fetch duplicates those rows. Deletion disables obsolete device bindings and
cancels pending connection attempts; a new robot may claim the released device. No part or unrelated cross-domain link
is silently deleted; no inferred fingerprint link is automatically accepted.
The retained-parts prompt survives reload and lists at most 24 parts per page; selecting
one reveals its actual node even when a service document still contains it. Deleting a
robot clears any selected category that was removed. A surviving selected part follows
its remaining containment path. An authenticated project remains writable independently
of the legacy onboarding completion flag, subject to server role checks.

### Service picker recovery and live updates

The first account expansion reads only I1's cache. A missing listing offers **Load documents**;
**Refresh documents** is explicit and disabled while a read/import is pending. **Refresh accounts**
finds newly connected Home accounts. Closing/reopening Add retains expanded accounts and choices.
Selecting a new document shows import progress, then reveals/focuses its real root. A failure stays
visible on subsequent clicks, with guidance to inspect Sources; no repeated sync is started.
Escape closes Add before affecting graph navigation; an outside click also closes it.

Committed source changes reach the current canvas through the existing project event stream.
A disconnected stream shows reconnection status; permission failures stop retrying and explain
that project access needs checking. Reconnection refreshes Solus graph data, never provider data.

## Sidebar, connection and SOL

Robot/sidebar connection state shows **Connecting…** immediately after confirmation returns;
existing `graph.changed` events reveal connected, failed or disconnected state. Failure remains
on the saved node and retry uses that node's identity. A session UUID is not receiving-data
proof. Serial-less device cards and sidebar both say “no serial number — identity is tied to
this USB port; keep it plugged in here”.

**Ask SOL about this node** opens the existing SOL window with the selected real entity as
subject. Selection alone makes no model call. The eventual send uses the current project,
Guide/Expert and action modes, budget/confirmation gates and entity mention. Changing selection
does not retarget an already submitted turn; account/project switches reject stale results.
Existing Import files/Add note actions keep their section/artifact handlers and limits. Broader
context actions for every arbitrary node remain follow-up work where no handler exists.

Hardware CONFIG uses its versioned editor and native-source subsection; CODE CONFIG uses its
environment view. Neither is editable as a note. Version conflict retains the local draft and
offers reload; deleted subject shows an honest 404 recovery state. Config deletion explains
binding effects and later GET does not recreate it.

Onshape account identity prefers authorized session display name, then email; without either,
show an honest provider account label rather than an opaque id. Account catalogs remain scoped
to their owner; teammate attached sources can appear without exposing private account catalogs.

## Authoritative refresh and measured performance

A delayed device seed GET must not overwrite a newer full hardware frame or revive after
account/project A→B→A. Every committed graph hint refreshes the current graph, even if a
timestamp-derived version and counts are unchanged. These operations read Solus state, never
implicitly synchronize providers.

Use per-confirmation and per-appearance performance marks. Repeated unplug/replug starts a new
span; simultaneous confirmations cannot consume each other's marks. Browser receipt-to-render
is labeled separately from physical plug-in latency. Confirm-to-node targets well under 500 ms;
sidebar feedback targets 100 ms. Report measured native results separately from component/API
fixtures and walk all 33 incoming QA steps against the merged build before claiming completion.

## Personal repository branch selection — SOLUSDEV-260

A Git repository's inspector exposes Branch with the active branch/commit, a
paginated branch picker and a reset-to-project-default action. Selecting a branch
shows loading while its snapshot is acquired, then refreshes the caller's graph and
SOL mention results. Failure leaves the previous view visible with an inline error.
The control states that selection affects only the current user. Other providers
show revision controls only when their capability is supported. ForgeTS is a named
local root; dependency packages are nested in presentation. Saved local working-copy
content is clearly distinguished from remote commit content in SOL results.
