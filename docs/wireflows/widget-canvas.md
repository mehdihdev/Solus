# Wireflow — Live Bench widget canvas (SOLUSDEV-235)

Live Bench (`MainScreen 'bench'`) becomes a canvas: a per-project grid of
CTR-01 slots (`docs/contracts/widget.md`) into which built-in widgets and
installed extension widgets are placed. The existing focused `LiveBenchWidget`
stays exactly where it is today — it is the default first slot — so a project
that never touches the canvas sees the Live Bench it already has. Runtime and
bridge: `docs/architecture/extensions-runtime.md`; page/window views and
developer mode: `extensions-runtime.md`.

Layout is persisted **server-side per (project, user)**:
`GET/PUT /api/v1/projects/{project_id}/widget-layout`, body
`{ slots: [{ ref, size }] }` where `ref` is `builtin:<widgetId>` or
`ext:<extensionId>` and `size` is `compact | standard | wide | full`. Two
people on the same project can arrange it differently; nobody's layout is
another's.

```
| rail | ---------------------------------------------------------------------- |
|      |   Live Bench                                          [ + Add widget ] |
|      |   <focus breadcrumb / device line as today>                            |
|      | ---------------------------------------------------------------------- |
|      |   ┌─ Live Bench ─────────────────────────────── ▭ ▾  ✕ ┐  ┌─ BOM  DEV ──── ▭ ▾ ✕ ┐ |
|      |   │                                                     │  │                      │ |
|      |   │      <LiveBenchWidget: signals, sim/real …>         │  │  <ExtensionFrame>    │ |
|      |   │                                                     │  │                      │ |
|      |   └─────────────────────────────────────────────────────┘  └──────────────────────┘ |
|      |   ┌─ Impact ──────────── ▭ ▾ ✕ ┐  ┌─ Reference ────────── ▭ ▾ ✕ ┐                   |
|      |   │                            │  │                            │                   |
|      |   └────────────────────────────┘  └────────────────────────────┘                   |
```

## Header

- Title `Live Bench` and the existing focus/device line are unchanged.
- **`+ Add widget`** (bordered button, right-aligned) opens the picker. Hidden
  while the layout is still loading from the server (no `loading` flash of an
  affordance whose result is unknown); disabled with tooltip "Offline — layout
  can't be changed" when the layout GET failed and there is no cached copy.

## Grid and slots

- Four slot sizes map to grid spans on a 4-column grid: `compact` = 1,
  `standard` = 2, `wide` = 3, `full` = 4 (rows auto-size; narrow windows drop
  to 2 columns and `wide` behaves as `full`). Coarse by design — the contract
  forbids widgets guessing at column counts, so the mapping lives here and
  nowhere else.
- Slot order is layout order (top-left first). Reordering is by the size
  menu's `Move up` / `Move down` (keyboard-friendly); drag-and-drop is not in
  this build.
- **Slot chrome** (a 32px bar above the widget body):
  - title — the built-in manifest `title`, or the extension's `name`; a
    `DEV` badge follows a dev registration's name; the extension's monochrome
    icon (host-reduced SVG) precedes the title for extension widgets.
  - `▭ ▾` size menu (`.popover-in`): `Compact · Standard · Wide · Full`
    (current checked; sizes below the widget's `minimum` are disabled with
    "Too small for this widget"), then `Move up`, `Move down`, and for
    extension widgets whose manifest has a window view, `Open in window ↗`.
  - `✕` remove — immediate, no confirm (re-adding is one click and nothing is
    lost: widgets hold no layout-bound state). The last remaining slot may be
    removed; that yields the empty state below.
  - The chrome reads `onStateChange` from built-in widgets and the
    ExtensionFrame state from extension widgets: a small muted `loading` dot
    while loading, a warn dot with tooltip when `error`.
- **Built-in widgets** (`discoverWidgets()`, CTR-01) render directly with
  `{ focus, onFocusChange, onStateChange }`. They are in-repo and trusted;
  `onFocusChange` writes go through the canvas to the focus store, as the
  contract requires.
- **Extension widgets** render an `ExtensionFrame` in `widget` mode
  (`src = solus-ext://<id>/<version>/<views.widget.entry>`). The frame's
  initial size comes from the manifest's `views.widget.preferred` when added;
  `minimum` gates the size menu. Focus reaches them as `focus.changed` bridge
  events (only with `focus.read`/`graph.read`), and `focus.propose` is the
  only way back — arbitrated by the canvas exactly like `onFocusChange`.
- Slot body states for extension widgets: skeleton while `loading` ("Loading
  BOM…" / "Downloading BOM…"), fade-in on `ready`, and an in-slot error card
  ("BOM didn't start." + `Reload`) on `error`. `blocked` (team policy, or the
  extension was uninstalled/disabled elsewhere) shows "Blocked by your team" /
  "BOM is no longer installed" with `Remove from layout`.

## Default layout

- With no saved layout for (project, user), the canvas is one slot:
  `{ ref: 'builtin:livebench', size: 'wide' }`. This is not written to the
  server until the user changes something, so a project that is never touched
  never accumulates layout rows.
- The Live Bench widget remains removable like any other; the empty state
  offers it back first.

## Picker (`+ Add widget`)

Modal (`.modal-backdrop-in` / `.modal-card-in`), 560px card, scroll region
capped at 60vh.

```
+-----------------------------------------------------------------+
| ADD WIDGET                                                   ✕  |
|-----------------------------------------------------------------|
| BUILT-IN                                                        |
|   ▦ Live Bench        Signals, sim and real modes    [ Add ]    |
|   ▦ Impact            Cross-domain change impact     [ Add ]    |
|   ▦ Reference         (already on canvas)            ADDED      |
|                                                                 |
| INSTALLED EXTENSIONS                                            |
|   [icon] BOM  ✓       Bill of materials …            [ Add ]    |
|   [icon] Scope Viewer  NEEDS RUNTIME                 —          |
|   [icon] Planner       disabled in this project      —          |
|                                                                 |
| DEVELOPER (THIS SESSION)                    ← only when present |
|   [icon] BOM  DEV     ~/code/solus-ext-bom          [ Add ]     |
+-----------------------------------------------------------------+
```

- **BUILT-IN**: every `discoverWidgets()` manifest, id-sorted, with its
  `title` and the widget's domains as a muted hint. A widget already on the
  canvas shows `ADDED` (muted) instead of `Add`; a widget may appear once.
- **INSTALLED EXTENSIONS**: every extension installed in this project whose
  manifest declares `[views.widget]`, from the install+policy snapshot. Rows
  carry the Store's publisher badge. Requirement hints follow `store.md`'s
  rules exactly: `NEEDS <KIND>` (mono, muted) when a required source kind is
  not connected, `disabled in this project` when enablement is off, `blocked
by your team` when policy blocks it; each of those disables `Add`. When the
  sources list is unavailable the requirement is shown as unmet — never
  assumed met. Empty section → "No installed extension adds a widget. Browse
  the Store →" (navigates to the Store).
- **DEVELOPER (THIS SESSION)**: dev registrations with a widget view. Present
  only while at least one exists.
- `Add` appends a slot at the end at the widget's preferred size, closes the
  modal, and scrolls the new slot into view; the slot enters with the
  `.screen-in` fade. Escape / ✕ close without change.

## Empty canvas

```
        ▦
   Nothing on your bench.
   Add the Live Bench widget, or any installed extension's widget.
   [ + Add widget ]     [ Restore default ]
```

- `Restore default` puts the single `builtin:livebench` slot back.
- Shown only after the layout has loaded (or offline with a cached copy that
  is empty); never during `loading`.

## Persistence and honesty

- **Optimistic**: every change (add, remove, resize, move) applies to the grid
  immediately and schedules one `PUT …/widget-layout` **debounced 800 ms**
  (the last write wins; rapid resizes coalesce). While a PUT is in flight a
  muted `Saving…` sits beside the header button; success clears it.
- **Failure**: the grid keeps the local layout and a muted note appears
  beside the header button — "Layout not saved — offline" (network) or
  "Layout not saved — try again" (server error) with a `Retry` link. The next
  change retries automatically. The note never disappears on its own until a
  PUT succeeds.
- **Loading**: on project open the canvas shows a skeleton grid (two
  placeholder slots) until the GET resolves; a 304/cached copy renders
  instantly. Never a flash of the default layout followed by the saved one.
- **Unknown refs are dropped, not crashed**: a stored `builtin:<id>` with no
  matching manifest (widget removed from the build) or an `ext:<id>` not in
  the install snapshot is skipped when rendering, kept out of the next PUT,
  and a one-line muted note under the header says "1 widget from your saved
  layout isn't available and was removed." (count-aware). Nothing is fabricated
  in its place.
- Dev registrations' slots (as shipped): the picker's Developer section lists
  acknowledged dev registrations that declare a widget view; an added `ext:<id>`
  ref IS persisted like any other (the server does not validate `ext:` refs
  against installs at write time); if the registration is removed the slot is
  pruned on the next load like any unknown ref.
- Layout is per (project, user): switching project swaps the layout (skeleton
  → saved); signing out clears any in-memory copy.
- Events: `widget_layout.changed { projectId, slots: N, refs: [...] }` on each
  successful PUT; `widget_layout.pruned { droppedRefs }` when unknown refs are
  removed.

## SOLUSDEV-262 L1 amendment

Session discovery continues while a project is open, regardless of Workspace focus. With
observed devices, one device-keyed telemetry composition remains mounted; focus narrows through
confirmed graph mapping instead of stopping discovery or changing data sources. Clearing focus
restores all current devices. Unrelated/unmapped focus states explain the absence of a confirmed
mapping. Starting/disconnected sessions remain visibly distinct from confirmed empty inventory.
Account/project switches discard previous in-flight results; request ordering cannot restore old
state. A genuinely empty bench offers Add → Hardware inline through the existing Workspace flow.

### SOLUSDEV-262 saved robot sessions

Live Bench's Manage connections dialog also searches saved physical robots in the current
project. A separate Connect button opens the existing robot-config session endpoint, resolving
its accepted protocol and calibration server-side. It never infers a driver from a USB bridge.
Search is bounded; explicit text search can find robots outside the first page. Missing or
incomplete configuration shows the existing setup error. Request progress prevents duplicate
starts. Account/project changes invalidate lists and pending responses. Existing session Stop
controls remain available. Connecting starts telemetry only; no motion control is introduced.

## SOLUSDEV-262 Runs and findings

The existing Live Bench tab contains a Runs panel: choose an active saved robot session and name
the capture, Start recording, then Stop. It never starts motion. Show count, origin and complete/
truncated/interrupted state. Saved runs open timestamp scrubbing and their retained artifact.
Select a baseline to compare aligned signals, unit compatibility, config/source changes and
evidence-linked differences. Findings use headline→explanation→detail with graph part/code/CAD
references; no-finding and missing-evidence are valid. Guide explains the evidence; Expert stays
terse. Optional SOL narration is an explicit metered action, never an automatic perpacket call.

Live Bench offers Signals, Scene and Runs views. Scene imports an explicitly chosen local
URDF/MJCF artifact for a saved robot; the user reviews joint-to-accepted-part mappings before
live motion visualization. Each model has display translation/rotation controls persisted per
account/project/model, and explicit reimport for revised source files. All robots share one
orbitable view. Missing meshes, stale mappings, WebGL failure and jointless geometry explain
what is unavailable. Display placement never sends a hardware command.

### SOLUSDEV-262 recorded sensor playback

Runs playback shares its exact recorded timestamp with numeric signals and sensor artifact
references. Each reference offers an explicit Open frame action. The scoped artifact content
route supplies bytes; camera preview accepts only PNG/JPEG/WebP (no SVG/HTML), bounded to8MiB.
LiDAR preview accepts bounded JSON {schema_version:1,unit:"m",points:[[x,y,z],...]} with at most
10000 finite triples and displays a labelled XY projection with Z range. No coordinates or
frames are synthesized. Missing/unsupported/unavailable media shows a reason. New timestamp,
run, project, or account clears media and cancels stale loads; object URLs are revoked.

Scene models offer explicit CAD mesh association: choose an existing model mesh key and a
project CAD leaf from the source picker, then confirm. Show observed microversion and queued,
current, stale or unavailable refresh status. Normal successful CAD sync updates only that mesh
while retaining model placement and valid joint mapping; no manual refresh is required for each
microversion. Unlinked model structures remain explicit imports.

Signal widgets retain accepted part names; unnamed detected actuator parts default to
RobotName-Motor-N using the stable observed bus address. Existing user/repo names are never
replaced. Charts display timestamped anomaly markers only from existing project/session-scoped
anomaly evidence. Missing evidence means no marker; unit conversion preserves marker timestamps.

## 2026-09-15 Live Bench presentation amendment

The user's four-phase UI brief replaces the Live Bench signals/scene/runs tabs with one view.
A header contains display Pause and evidence-derived STREAMING / PAUSED / NO STREAM status.
The left column is approximately 300 px: SCENE + Spawn, a dark dotted scene, explicit absent
camera/depth sentences, and a footer that distinguishes actual CAD links from missing bindings.
The right pane uses a responsive grid of signal windows with an actual eight-second history,
large current values, inline persisted names, filled sparklines and amber `no unit` when unknown.
Clicking a signal scopes it; renaming does not accidentally scope it. Placeholder names/units
produce the brief's explanation and a link into hardware identity confirmation. Findings follow
under LIVE REASONING, with unavailable evidence distinguished from no observed findings.
Capture/playback and installed widgets remain reachable inline rather than hidden behind tabs.
Channel additions/removals update automatically; pausing display does not stop hardware, mutate
session configuration or bypass a confirmation gate.
