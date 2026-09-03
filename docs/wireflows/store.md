# Wireflow — Store (SOLUSDEV-235)

The Store is where a project's capabilities are installed. It is `MainScreen
'store'` in the workspace shell — a rail item (the `+` glyph, after Team) and
the topbar breadcrumb `Home / <project> / Store`. Everything on it is scoped to
the OPEN PROJECT: installs, enablement, and run frequency are per project, and
suggestions are gated on the sources connected to that project — never on what
sells. Without an open project the screen asks the user to pick one (same
guard as Sources).

Source of record for the visuals: the four design screenshots attached to the
ticket (catalog; detail › Overview / Settings / Permissions).

```
| rail | topbar: Home / <project> / Store [/ <extension>]                         |
|      | ---------------------------------------------------------------------- |
|      |   Store                                    [▦ ≡]  [+ Create extension] |
|      |   Capabilities are installed, not built in. Suggestions come from       |
|      |   what's connected — never from what sells.                            |
|      |   INSTALLED                                                             |
|      |   [card][card]                                                          |
|      |   [card][card]           (See all installed (N))                        |
|      |   POPULAR EXTENSIONS                                                    |
|      |   [card][card]                                                          |
```

## Catalog (default view)

- **Header**: title, subtitle, a grid/list layout toggle (radiogroup, icon
  buttons), and the primary `+ Create extension` button.
- **INSTALLED**: two-column card grid (single column in list layout). Shows
  the first 4 installed extensions; `See all installed (N)` expands to all,
  `Show fewer` collapses. Empty → "Nothing installed in this project yet."
- **POPULAR EXTENSIONS**: every extension not installed in this project.
  Empty → "Everything in the catalog is installed in this project."
- **Card**: icon tile · name · publisher badge (`SOLUS ✓` in the ok color, or
  `COMMUNITY` muted) · one-line summary · right-aligned status:
  - `● INSTALLED` (ok dot) when installed here;
  - `NEEDS <KIND>` (mono, muted) when a required source is missing — groups of
    alternatives join with `|` (`NEEDS CAD|EDA`), conjunctions with `+`;
  - `AVAILABLE` when installable now.
    The whole card is a button (`Open <name>`), keyboard-operable.
- **Requirements follow reality**: source kinds are derived from the project's
  connected sources (`github/gitlab → CODE`, `kicad/altium → EDA`,
  `onshape → CAD`, `ros → RUNTIME`, `canbus → CANBUS`). When the sources list is
  unavailable (offline / unreachable API) a note says requirements are shown as
  unmet, rather than pretending they are met.
- **+ Create extension**: opens a dialog explaining the manifest model and
  linking the manifest docs; the authoring flow itself is not in this build and
  the dialog says so. (Design TBD — see completion report.)

## Extension detail (click a card)

Replaces the catalog in place; the breadcrumb becomes `Store / <name>`. The
`← Store` link (and the rail's Store button) return to the catalog.

- **Header**: 56px icon tile · name (h1) · publisher badge · meta line
  `<Publisher> · v<version> · <N installs | — installs> · updated <relative>`.
  Install counts render as `—` until the catalog service reports real ones
  (SOLUSDEV-152: never a fabricated number).
- **Header actions**:
  - installed → `Disable` / `Enable` (toggles enablement here) and `Uninstall`
    (danger). Uninstall opens a confirm: "Uninstall <name>? Its widgets and
    checks leave this project. Graph data it already added stays. Your settings
    are kept if you reinstall." → `Uninstall extension` returns to the catalog.
  - not installed → `Install` (primary). Disabled with a `NEEDS <KIND>` label
    while a required source is missing.
- **Tabs** (`tablist`): Overview · Settings · Permissions.

### Overview

Two columns: content (flex) and a 260px card stack.

- **WHAT IT ADDS**: one row per contribution — kind icon (widget ▦, SOL
  grounding ◉, check ✓, panel ≡), title, one-line detail.
- **IN THIS PROJECT**: a status card derived from install state only — `IDLE`
  ("No activity in this project yet."), `DISABLED`, or `NOT INSTALLED`. No
  run history is fabricated; a real timeline arrives with the backend.
- **REQUIRES** card: each requirement group with a met (ok) / unmet (warn) dot
  and its long name ("A CAD source (Onshape) or An EDA source (KiCad,
  Altium)"); "No connected source required." when empty.
- **CREDITS** card: `This cycle —` until spend is metered (then `N`) ·
  `Per run, typical ~N` (or `none` for extensions that never call a model).
  Credit-denominated (ADR-018).
- **LINKS** card: Documentation ↗ · Source ↗ · Report an issue ↗. Only https
  URLs render as anchors (`isSafeExternalUrl`); main's shared window-open
  handler (`main/externalUrl.ts`) opens https in the OS browser and drops
  everything else.

### Settings

- `Enable in this project` — switch. "Turn this extension's widgets and checks
  on or off here."
- `Run frequency` — select: On every sync · Hourly · Daily · Manual only.
  "When this extension re-evaluates."
- Footnote: "Settings apply to this project only. Team defaults are set by an
  owner." Controls are disabled with "Install this extension to change its
  settings." while not installed.

### Permissions

- One row per declared scope: icon tile · title · detail (or "Not yet
  requested") · `GRANTED` (ok) / `NOT ASKED` (muted). Scopes are a closed set
  (`graph.read`, `telemetry.read`, `sources.read`, `findings.write`); Solus code
  decides what each permits (CLAUDE.md §7).
- Muted footnote: "These are the scopes the extension declares. Solus
  enforces scopes server-side; per-project grant controls arrive with the
  Store backend." — the statuses are declared, not a live grant record.
- Warn-tinted note: "Extensions never write to hardware directly — anything
  that would move a motor goes through the approval queue, per your team
  instructions." (CTR-03.)

## State (this build)

- Catalog: in-repo build-time data (`features/extensions/extensions.catalog.ts`),
  the same stance as widget manifests (CTR-01). First-party entries name
  capabilities that exist in the repo; nothing is invented as a product.
- Install state: `extensionsStore` (Zustand, localStorage), keyed
  `projectId → extensionId → {installed, enabled, runFrequency}`. Bundled
  extensions start installed. The selected extension is navigation state and is
  not persisted. Rehydration is sanitized (known extension ids, well-formed
  state only) and the whole store is reset on sign-out (WS-01 precedent) and the
  selection cleared on project switch.
- `useExtensions(projectId)` is the backend seam: catalog × install state ×
  connected sources → `ExtensionView[]`. The Store API replaces its inputs, not
  its consumers.
