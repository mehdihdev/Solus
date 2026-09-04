# Wireflow — Extensions runtime (SOLUSDEV-235)

Where an installed extension shows up once the Store (`store.md`) has installed
it: the permissions step that precedes an install, the page view screen, the
window view, developer mode, and the update flow. Architecture and the bridge
protocol: `docs/architecture/extensions-runtime.md`. The widget view lives on
the Live Bench canvas: `widget-canvas.md`. Everything here is scoped to the OPEN
PROJECT; without one, the surfaces below are not reachable (the rail entries do
not render).

Motion reuses the app-wide classes in `assets/main.css`: screens enter with
`.screen-in`, menus with `.popover-in`, dialogs with `.modal-backdrop-in` /
`.modal-card-in`. An extension frame fades in with the `.screen-in` timing
when its state becomes `ready`; a skeleton holds the space while `loading`.
`prefers-reduced-motion` disables all of it.

## 1. Permissions step (Store install flow)

Entered from the detail page's `Install` (and from `Update` when the new
version widens scopes — §5). Modal over the Store, 520px card.

```
+-----------------------------------------------------------------+
| INSTALL BOM                                        v1.2.0    ✕  |
| by Solus ✓                                                      |
|-----------------------------------------------------------------|
| BOM asks for                                                    |
|   ◉ Read the context model          graph.read                  |
|     Entities, relations and neighbourhoods of this project.     |
|   ◉ List connected sources          sources.read                |
|     Which tools are connected and when they last synced.        |
|                                                                 |
| It may connect to                                               |
|   ↗ https://api.octopart.com                                    |
|                                                                 |
| Nothing else. Solus performs every call on its behalf with your |
| account; the extension never receives your credentials.         |
|                                                                 |
| Privacy policy ↗                                                |
|-----------------------------------------------------------------|
|                              [ Cancel ]  [ Grant and install ]  |
+-----------------------------------------------------------------+
```

- **Scopes**: one row per declared `permissions.scopes` entry, in manifest
  order — icon tile, human title, the raw scope in mono, one-line detail.
  Titles and details are Solus copy keyed by scope (the closed set in
  `extension-manifest.md`), never text from the manifest.
- **Network**: one row per `permissions.network` origin, rendered as text
  (not a link). Section hidden when the list is empty.
- **No permissions**: when both lists are empty the body reads "BOM asks for
  nothing. It runs entirely inside its sandbox." and the button is `Install`.
- **Privacy policy ↗**: opens the bundle's `store.privacy_policy` in the
  in-app markdown reader (it is a bundle file, not a URL). Required by the
  contract whenever a scope or origin is declared, so it is always present
  when the lists are non-empty.
- `Grant and install` → `PUT /projects/{project_id}/extensions/{id}` with
  `{ version, granted_scopes: [<every listed scope>], granted_network:
[<every listed origin>] }` (`201`), then the desktop installer runs. Grants
  are all-or-nothing in this build: the button grants exactly the declared
  set. Per-scope toggles are not offered (a partial grant would make
  every extension handle `scope_denied` on its core path — the Permissions tab
  shows the granted set afterwards and `Uninstall` is the revoke).
- Button states: `Installing…` (disabled) while the server row is created;
  the modal closes on success and the detail header switches to
  `● INSTALLED`, with the frame download continuing in the background (the
  Overview "IN THIS PROJECT" card shows `DOWNLOADING` until the bundle is
  cached, then `IDLE`).
- Failure: inline error above the buttons — "Couldn't install. Try again."
  (server), "Blocked by your team." (policy, button disabled), "Requires
  Solus <min_solus> or newer." (host floor). Never a fabricated success.
- Escape / ✕ / Cancel: nothing is created.

### Permissions tab (after install)

`store.md`'s Permissions tab now reads the real grant record: each row is
`GRANTED` (ok) with the grant date, or `NOT GRANTED` (warn) when a newer
version added a scope the user has not accepted (§5). The footnote becomes
"Solus enforces these scopes at every call; revoke by uninstalling."

## 2. Page view screen

An extension with `[views.page]` gets a rail entry and a screen
(`MainScreen 'ext-page'`, keyed by extension id).

```
| rail      | ---------------------------------------------------------------- |
| Home      |   [icon] BOM  DEV                       [ Open in window ↗ ]     |
| Overview  |   by Solus ✓ · v1.2.0                                            |
| Context   | ---------------------------------------------------------------- |
| Sources   |                                                                  |
| Live Bench|                                                                  |
| SOL       |                    <iframe fills the screen>                     |
| Team      |                                                                  |
| ▣ BOM     |  ← page entries, directly ABOVE the Store `+`                    |
| + Store   |                                                                  |
```

- **Rail entry**: inserted between `Team` and the Store `+`, one per
  installed+enabled extension with a page view, ordered by install date.
  Icon = the manifest's `views.page.icon` reduced by the host to a path-only
  SVG subset (paths, fill, viewBox — no scripts, no external refs, no
  `<foreignObject>`, no filters), drawn with the rail's current color like a
  built-in icon. Label = `views.page.label`. Dev registrations get a small
  `DEV` corner mark on the icon. The rail shows at most 8 page entries (as
  shipped, SOLUSDEV-235 EXT-14); the rest stay reachable from the Store. A
  `▾ More` popover for the overflow is a follow-up.
- **Header**: 24px icon tile · extension name · `DEV` badge (mono, warn
  tint) when a dev registration · publisher badge · `v<version>` (or `dev`).
  Right: `Open in window ↗` only when the manifest also declares
  `[views.window]` (§3).
- **Frame**: one `ExtensionFrame` in `page` mode filling the remaining
  height. `src = solus-ext://<id>/<version>/<views.page.entry>`.
- **States**:
  - `loading` — skeleton (header renders immediately; body is a muted panel
    with "Loading BOM…"; if the bundle is still downloading, "Downloading
    BOM…" instead).
  - `ready` — frame fades in.
  - `error` — centered card: "BOM didn't start." + the step that failed
    ("its page entry was not found", "it did not respond in 10 s", "the
    downloaded bundle didn't match the registry") + `Reload` and
    `Open in Store`. Dev registrations also show the failing request path.
  - `blocked` — "Blocked by your team." + `Open in Store`. Shown when the
    install+policy snapshot removes or blocks the extension while the screen
    is open; the frame is unmounted, not just hidden.
  - **disabled** in this project → the rail entry is not rendered; a deep link
    to the screen shows "BOM is disabled in this project." + `Open in Store`.
- Switching projects while on this screen always leaves it for Overview (as
  shipped — the same rule the Store detail page follows); remounting against
  the new project when it has the extension too is a follow-up.
- `View` menu (`project-topbar.md`) does not list page entries yet (follow-up).

## 3. Window view

An extension with `[views.window]` can run in its own OS window
(`Open in window ↗` on the page screen, or the widget slot menu when the
extension has no page view).

```
+--------------------------------------------------+
| ● ● ●   BOM                                 DEV  |   ← OS title bar, title = views.window.title
|                                                  |
|                                                  |
|            <iframe fills the window>             |
|                                                  |
|                                                  |
+--------------------------------------------------+
```

- Main creates a second `BrowserWindow` (the SOL orb pattern) loading the
  renderer at `#/ext-window/<id>`; the renderer mounts one `ExtensionFrame` in
  `window` mode plus a BridgeHost bound to the project that was open when the
  window was requested.
- **Title** from `views.window.title` (≤ 60 chars, rendered by the OS; dev
  registrations append ` — DEV`). **Size** from `views.window.width/height`,
  clamped to 320–4096 px and to the current display's work area; resizable;
  remembers nothing between opens (manifest size every time).
- Native frame, native drag and close; `Cmd/Ctrl+W` closes. One window per
  (project, extension): a second `Open in window` focuses the existing one.
- Closing the main window closes every extension window. Signing out closes
  them. A project switch in the main window sends `project.changed` and then
  remounts the window's frame against the new project if the extension is
  installed and enabled there; otherwise the window shows "BOM isn't
  installed in <project>." with `Close`.
- States as §2 (`loading` skeleton, `ready` fade, `error` card, `blocked`),
  rendered inside the window; the `error` card's `Open in Store` focuses the
  main window and navigates it.
- Nothing in the window is a drag region except the OS title bar; there is no
  in-window menu bar (`autoHideMenuBar`).

## 4. Developer mode

Settings → **Developer** section (new, after Integrations; account-level like
the rest of Settings but the loaded extensions apply to whichever project is
open).

```
DEVELOPER
  Load an unpacked extension from a folder on this computer. It runs with a
  DEV badge, is never published, and is forgotten when Solus quits.

  [ Load unpacked extension… ]

  LOADED THIS SESSION
  ┌────────────────────────────────────────────────────────────────────┐
  │ [icon] BOM  DEV        bom · 1.3.0-dev                             │
  │ ~/code/solus-ext-bom                                               │
  │ widget · page · window          [ Reload ] [ Remove ]              │
  ├────────────────────────────────────────────────────────────────────┤
  │ ⚠ ~/code/broken-ext — not loaded                                   │
  │   views.page.entry: must be a relative path with no `..` segments  │
  │   store.privacy_policy: required when permissions are declared     │
  │                                    [ Pick again ] [ Remove ]       │
  └────────────────────────────────────────────────────────────────────┘
```

- **Load unpacked extension…** → OS folder picker (main). Refused folders
  (inline, warn): "Pick the extension's folder, not your home folder." (`~`),
  "That folder belongs to Solus." (`~/.solus` or anything under
  `~/.solus/extensions/`), "Pick a folder, not the whole disk." (a root).
- Validation problems are the contract's dotted-path strings, one per line,
  verbatim — identical to what the publish validator would say. The row stays
  listed as "not loaded" so the developer can fix and `Pick again`.
- A `schema_version` newer than the host → "Needs a newer Solus (manifest
  schema 2)." — listed, not loaded.
- Successful load shows the permissions step (§1) with a `DEV` badge in its
  title; grants are session-local and never sent to the server. Then the
  extension appears everywhere an installed one would: rail (page), widget
  picker under "Developer (this session)", `Open in window`. Every surface
  carries the `DEV` badge.
- **Reload**: re-validates the manifest; on success remounts every frame of
  `dev:<id>` (widgets, page, window) with a fresh cache-busting nonce. On
  failure the frames stay on the last good load and the problems appear in the
  row.
- **Remove**: drops the registration, unmounts frames, removes rail/picker
  entries. Session-only widgets vanish from the canvas (they were never in the
  saved layout).
- The DEV badge tooltip (page header, slot chrome, window) shows the
  registered path and a live count of dropped and refused bridge messages
  with their codes — the only place refusals are surfaced in Solus chrome.
- Coexistence: a dev registration and an installed published extension with
  the same id both appear, distinguishable by the badge. The dev one never
  inherits the published one's grants.
- Not offered: publishing, signing, packaging. The section links to
  `docs/extensions/` ("How to publish ↗", https).

## 5. Update available

Installs pin a version. When the registry has a newer visible version:

```
 Store card                          Detail header
 ┌──────────────────────────┐        [icon] BOM  ✓  v1.2.0 → 1.3.0 available
 │ [icon] BOM        ✓      │        [ Update to 1.3.0 ]  [ Disable ]  [ Uninstall ]
 │ Bill of materials …      │
 │           ● INSTALLED ↑  │        WHAT'S NEW  (the version's changelog, markdown, text-rendered)
 └──────────────────────────┘        PERMISSIONS  + telemetry.read  (new — you'll be asked)
```

- Card: `● INSTALLED ↑` (the arrow in the accent color, tooltip "Update
  available: 1.3.0"). Catalog header, when any installed extension has an
  update: a muted line "N updates available" — no auto-update, no badge on
  the rail.
- Detail header: meta line shows `v<pinned> → <latest> available`; primary
  action becomes `Update to <latest>`.
- **Scopes unchanged or narrowed** → `Update to 1.3.0` swaps the install row
  (`PUT …/extensions/{id} { version, granted_scopes, granted_network }` → `200`), the installer downloads and
  verifies the new bundle beside the old one, frames remount on the new
  version once cached, and main removes the old directory. Until the download
  completes the old version keeps running — "Updating…" in the header, no
  broken state in between.
- **Scopes or network origins widened** → `Update to 1.3.0` opens the
  permissions step (§1) titled `UPDATE BOM`, listing only the **new** scopes
  and origins under "1.3.0 additionally asks for", with the existing grants
  summarised beneath. `Grant and update` → as above. `Cancel` keeps the pinned
  version running with no change.
- A version that was withdrawn from the registry after being installed keeps
  running from the cache; the card shows `● INSTALLED` with a muted "no longer
  in the catalog" and `Update` is absent.
- Offline: the update affordance is hidden rather than shown stale (the
  catalog is server-derived; without it the Store shows its existing offline
  note).
- Events: `extension.updated { id, from, to, regranted: boolean }`;
  `extension.update_declined` when the permissions step is cancelled.
