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
