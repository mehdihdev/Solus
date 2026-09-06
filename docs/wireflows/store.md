# Wireflow — Store (SOLUSDEV-235)

The Store is where a project's capabilities are installed. It is `MainScreen
'store'` in the workspace shell — a rail item (the `+` glyph, after Team) and
the `View → Store` menu (see `project-topbar.md`). Everything on it is scoped to
the OPEN PROJECT: installs, enablement, and run frequency are per project, and
suggestions are gated on the sources connected to that project — never on what
sells. Without an open project the screen asks the user to pick one (same
guard as Sources).

Source of record for the visuals: the four design screenshots attached to the
ticket (catalog; detail › Overview / Settings / Permissions).

```
| ● ● ●  [ ▣ <project> ▾ ]                                                        |
| Solus  View  Robot  Help                    (bridge) [search] 🔔 Sign out       |
| rail | ---------------------------------------------------------------------- |
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
- **Card**: icon tile · name · publisher badge (`<PUBLISHER> ✓` in the ok
  color for a verified publisher, or `COMMUNITY` muted) · one-line summary ·
  right-aligned status:
  - `● INSTALLED` (ok dot) when installed here, with `↑` in the accent color
    (tooltip "Update available: <version>") when the pin is behind the latest
    approved version;
  - `NEEDS <KIND>` (mono, muted) when a required source is missing — groups of
    alternatives join with `|` (`NEEDS CAD|EDA`), conjunctions with `+`;
  - `BLOCKED` when the team policy refused an install (server `403
extension_blocked`);
  - `AVAILABLE` when installable now.
    The whole card is a button (`Open <name>`), keyboard-operable.
- **Updates line**: when any install has an update, a muted "N updates
  available" line sits under the header — no auto-update, no rail badge.
- **Requirements follow reality**: source kinds are derived from the project's
  connected sources (`github/gitlab → CODE`, `kicad/altium → EDA`,
  `onshape → CAD`, `ros → RUNTIME`, `canbus → CANBUS`). When the sources list is
  unavailable (offline / unreachable API) a note says requirements are shown as
  unmet, rather than pretending they are met. When the Store API itself is
  unreachable the catalog is EMPTY and a note says nothing can be installed —
  never a stale or invented catalog. "Loading the catalog…" holds the space
  during the first read.
- **+ Create extension**: opens a dialog explaining the manifest model and
  linking the manifest docs; the authoring flow itself is not in this build and
  the dialog says so. (Design TBD — see completion report.)

## Extension detail (click a card)

Replaces the catalog in place. The `← Store` link (and the rail's Store button
or `View → Store`) return to the catalog.

- **Header**: 56px icon tile · name (h1) · publisher badge · meta line
  `<Publisher> · v<pinned or latest> · <N installs | — installs> · updated
<relative>`. The version reads `v1.2.0 → 1.3.0 available` when the install
  is behind; an install whose version left the catalog appends `no longer in
  the catalog`. Install counts come from the catalog's aggregate and render as
  `—` when it reports none (SOLUSDEV-152: never a fabricated number).
- **Header actions**:
  - installed → `Update to <latest>` (primary, only when an update exists),
    `Disable` / `Enable` (toggles enablement here) and `Uninstall` (danger).
    Uninstall opens a confirm: "Uninstall <name>? Its widgets, tools and the
    graph data it added leave this project. Its settings are removed too."
    (SOLUSDEV-246 "no orphans": the server soft-deletes the bundle's declared
    graph kinds, drops its settings, storage and canvas slots —
    `docs/api/widget-bundles.md` §5.) → `Uninstall extension` DELETEs the
    install, removes the cached bundle from this machine, and returns to the
    catalog; a refusal (`403 forbidden` for a viewer) keeps the page with the
    reason.
  - not installed → `Install` (primary), which opens the **permissions step**
    (`extensions-runtime.md` §1). Disabled with a `NEEDS <KIND>` label while a
    required source is missing, with "Blocked by your team" when the team
    policy blocks it, and while the manifest is still loading.
  - A one-line status under the header reports the outcome of the last write:
    the bundle note after an install ("Installed in this project. The bundle
    downloads when you open it in the Solus desktop app." outside Electron;
    "…could not be cached on this machine (<reason>)" when main refused it), or
    the route-plan error mapped to plain text (`extension_blocked` → "Blocked
    by your team.", `validation_error`, `scope_denied`, `forbidden`,
    `not_found`, `rate_limited`; anything else → "Couldn't reach Solus.").
- **Permissions step**: lists every declared scope (Solus copy per scope, the
  raw scope in mono) and network origin, links the bundle's privacy policy,
  and grants exactly the declared set on `Grant and install` (`PUT
/projects/{id}/extensions/{slug}` with the latest version), then fetches the
  bundle and hands it to the desktop installer. `Cancel` / ✕ / Escape create
  nothing. A server refusal shows inline in the step.
- **Update flow**: `Update to <latest>` PUTs the newer version with the
  CURRENT grants. `409 grants_required` reopens the permissions step titled
  `Update <name>`, listing only the additions ("<version> additionally asks
  for"); `Grant and update` retries with the widened set. Otherwise the pin
  moves and the new bundle is cached beside the old one.
- **Tabs** (`tablist`): Overview · Settings · Permissions.

### Overview

Two columns: content (flex) and a 260px card stack.

- **WHAT IT ADDS**: one row per view the manifest really declares — `Widget`
  (▦), `Page: <label>` (≡), `Window: <title>` (▢) — plus a `Permissions` (✓)
  summary row ("2 scopes · 1 network origin", or "Asks for nothing"). Nothing
  is invented beyond `[views]`. Before the manifest is fetched the catalog's
  view kinds stand in without labels, under "Loading the extension's
  manifest…".
- **IN THIS PROJECT**: a status card derived from the install row only —
  `IDLE` ("No activity in this project yet."), `DISABLED`, `BLOCKED BY TEAM`,
  or `NOT INSTALLED`. No run history is fabricated; a real timeline arrives
  with the runtime.
- **REQUIRES** card: each requirement group (`extension.requires`) with a met
  (ok) / unmet (warn) dot and its long name ("A CAD source (Onshape) or An EDA
  source (KiCad, Altium)"); "No connected source required." when empty.
- **CREDITS** card: `This cycle —` until spend is metered per extension (then
  `N`). Credit-denominated (ADR-018). No per-run estimate — there is no data
  source for one.
- **LINKS** card: Documentation ↗ · Terms ↗ · Report an issue ↗ from
  `manifest.store.links`; "No links published." when empty. Only https URLs
  render as anchors (`isSafeExternalUrl` — manifests are developer input);
  main's shared window-open handler (`main/externalUrl.ts`) opens https in the
  OS browser and drops everything else.

### Settings

- `Enable in this project` — switch. "Turn this extension's widgets and checks
  on or off here." (`PATCH { enabled }`.)
- Then one row per `[[settings.fields]]` entry of the PINNED manifest, keyed by
  type: `boolean` → switch, `select` → select over `options`, `number` →
  number input honouring `min`/`max`, `string` → text input. Values are the
  install row's `settings` over the manifest defaults. Edits are saved as one
  object (`PATCH { settings }`) once typing pauses (400 ms); a server refusal
  (`422 validation_error`) shows under the fields. "This extension has no
  settings of its own." when the manifest declares none.
- Footnote: "Settings apply to this project only. Team defaults are set by an
  owner." Controls are disabled with "Install this extension to change its
  settings." while not installed.

### Permissions

- One row per declared scope: icon tile · title · detail · `GRANTED` (ok) when
  the install row's `granted_scopes` holds it, `NOT GRANTED` (warn on an
  install that lacks it — a newer version added it; muted before an install).
  Scopes are the contract's closed set of eight (`graph.read`, `telemetry.read`,
  `sources.read`, `findings.write`, `sol.ask`, `storage.own`, `focus.read`,
  `focus.write`); Solus code decides what each permits (CLAUDE.md §7).
- **MAY CONNECT TO**: one row per `permissions.network` origin with the same
  `GRANTED` / `NOT GRANTED` from `granted_network`.
- Muted footnote: "Grants are per project. Solus enforces these scopes at every
  call; revoke by uninstalling." — the statuses are the live grant record.
- Warn-tinted note: "Extensions never write to hardware directly — anything
  that would move a motor goes through the approval queue, per your team
  instructions." (CTR-03.)

## State (this build)

- Catalog: the server's (`GET /extensions`, docs/api/extensions.md §4.1),
  walked across pages (capped at 500 rows) on open and on `refresh()`. Only
  extensions with an approved version appear; nothing is bundled in the build.
- Install state: the server's install rows (`GET /projects/{id}/extensions`,
  §6.1) — pin, enablement, settings, grants, update availability, team policy —
  re-read every 10 s like the Sources page so a teammate's install, a block,
  or a newly approved version shows up without a click. A single failed
  refresh keeps what is on screen; only a session that cannot fetch at all
  (or an API unreachable from the start) is `offline`. Nothing is persisted
  locally: `extensionsStore` holds ONLY the selected extension (navigation),
  reset on sign-out (WS-01 precedent) and cleared on project switch.
- Manifests: an install carries its PINNED manifest on the row; an uninstalled
  extension's manifest is fetched from the detail route (§4.2) when its page
  opens, so the tabs and the permissions step render real declarations.
- Blocked: an install refused with `403 extension_blocked` marks the slug
  blocked for the session; an install row reports the policy directly.
- `useExtensions(projectId)` is the backend seam: server catalog × server
  install rows × connected sources → `ExtensionView[]` plus the write actions
  (`install`, `update`, `uninstall`, `setEnabled`, `setSettings`,
  `loadDetail`, `refresh`), each doing the server write first and the
  machine-local bundle step second, and reporting what actually happened.
