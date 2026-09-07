# Wireflow — Workspace (SOLUSDEV-242)

Authority: the approved combined Workspace request (SOLUSDEV-242); the design spec cited
previously (`docs/design/screens/SPEC.md`) does not exist in the repository.
Architecture: `docs/architecture/workspace-navigation.md`; routes:
`docs/api/workspace.md`, `docs/api/solus.md`, API.md §2.5.
This replaces the W1 panel/list wireflow. Implementation lands in four ordered
phases; the old panel exists only until the Phase 2 migration is integrated.

```
| rail | Add  /  Workspace › selected ancestor › current level | inspector |
|      |                                                       |           |
|      |         typed node cards and distinct cross-links      | focus     |
|      |                    .solus (center)                     | neighbors |
|      |                                                       |           |
|      | hover + scroll to enter · scroll out to return          |           |
|      | real graph counts                  Previous / Next     |           |
```

## Navigator

A new project's only top-level node is `.solus`, centered. The Add button remains
available. No empty-state overlay covers it and no `.solus` left panel remains.
Connected documents and manual robots appear around it. Cards are draggable;
positions are shared by the project and remain after reload. Saving/error/conflict
status is visible. Retry after a conflict saves only the user's moved nodes onto
the latest layout; it does not discard teammate positions silently.

Hover a card and scroll inward to reveal its immediate children with a transition
from that card. Scroll outward goes up one level. Double-click, explicit enter/back
controls, keyboard and breadcrumbs provide equivalent navigation. Clicking any
entity updates the shared focus, including Live Bench. Leaves select without
zooming. Zoom never triggers source synchronization. Reduced-motion settings are
respected. A maximum of 24 cards render at once; explicit page controls reveal
additional siblings. Cross-domain links use distinct dashed styling, projected
onto visible ancestor cards; outside-level connections remain discoverable.

## `.solus`

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

Top-left **Add** opens a panel with **From a service** and **Hardware** tabs.
From a service lists the accounts connected in Home and cached document/repo
choices. Reopening a dropdown reuses its loaded listing. Missing cached data is
an honest empty state with an explicit refresh action; opening the panel itself
never spends provider quota. Selecting a new document creates a project node and
starts its first sync. Re-selecting an existing node only focuses it. A second
Onshape document or Git repository creates a second root of that type.

Onshape: document → assemblies → parts. Git: repository → directories → files.
Loading/sync failures are shown on the selected source; unrelated nodes remain
usable. No provider call occurs on graph selection, zoom or layout changes.

## Physical Robot

Add → Hardware offers manual creation of a Physical Robot now; later R1/R2
onboarding connects to the same service. The five-card Hardware surface is specified in
`hardware-onboarding.md`.
Add → Hardware also offers **Find a sourced part** (STORE ST5, `sourcing.md`):
the same sourcing panel the BOM uses, defaulting to *From CAD* so SOL derives
the torque from one of the project's assemblies; the selected candidate enters
the chosen robot category as a PLANNED part and the robot view reloads.
Disabled while the project is offline. Default name is the project's name,
editable inline. Multiple robots coexist with independent names and containment.
Enter a robot to see Sensors, Actuators / motors, Controllers, End effectors,
Power, Structure, Wiring; enter a category to see its parts. Empty categories
show an honest empty state. Hardware configuration and transport references
remain empty until those features supply their contracts.

Deleting a robot shows a concrete confirmation and explains that its parts are
retained. After confirmation the parts remain visible as unassigned, with a
prompt to attach them to another robot. No part or unrelated cross-domain link
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
