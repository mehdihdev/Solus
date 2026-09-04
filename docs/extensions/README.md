# Solus extensions — developer documentation

Extensions add views to a Solus project: a **widget** on the Live Bench canvas, a **page** in the
rail, and/or a detached **window**. Each view is plain HTML/JS/CSS that Solus loads inside a
sandboxed `<iframe>`; the only way out of that sandbox is a small, permission-checked
`postMessage` API (the _bridge_) that the host executes on the extension's behalf with the signed-in
user's session and the open project's scope.

Anyone with a Solus account can publish. Every published version passes an automated review
(manifest contract, bundle caps, static content checks) before it becomes visible; the "verified"
badge is a separate, manual decision by Solus staff.

| Page                                  | What it covers                                                                                     |
| ------------------------------------- | -------------------------------------------------------------------------------------------------- |
| [Getting started](getting-started.md) | A complete "Hello widget", loading it in developer mode, then adding a page (with icon) and window |
| [Manifest reference](manifest.md)     | Every table and field of `extension.toml`, caps, scopes, settings, `[store]`, validation messages  |
| [Bridge API](bridge-api.md)           | The runtime API from the frame's side: handshake, methods, events, limits, CSP, errors             |
| [Publishing](publishing.md)           | Packaging the zip, `POST /extensions/publish`, review, versions, updates, unpublishing, the badge  |

Authority: the manifest is a contract (`docs/contracts/extension-manifest.md`, TypeScript in
`packages/shared-types/src/extension-manifest.ts`, Python in
`packages/contracts/python/solus_contracts/extension_manifest.py`); the runtime is
`docs/architecture/extensions-runtime.md`; the routes are `docs/api/extensions.md`; the decision is
`DECISIONS.md` ADR-035. Where this documentation and those disagree, those win — and please file it.

## What an extension is

- **A bundle**: a folder (zipped for publishing) with `extension.toml` at its root plus the HTML,
  JS, CSS, images, fonts and Markdown it needs. Nothing in a bundle is ever executed by Solus itself;
  files are served verbatim to the frame.
- **One to three views**, declared in the manifest:
  - `widget` — a slot on the Live Bench canvas; sized by a coarse hint (`compact | standard | wide | full`).
  - `page` — a full screen with an entry in the rail; needs a monochrome SVG icon and a label.
  - `window` — the same kind of frame in a second OS window, sized from the manifest.
- **A sandbox**: `<iframe sandbox="allow-scripts">` served from `solus-ext://<id>/<version>/…`.
  The frame has an opaque origin, no network (`connect-src 'none'`), no remote scripts, no nested
  frames, no Node, no preload, and never sees a token or an API URL.
- **The bridge**: JSON messages over `postMessage`. Each method is tied to one scope from a closed
  set (`graph.read`, `telemetry.read`, `sources.read`, `findings.write`, `sol.ask`, `storage.own`,
  `focus.read`, `focus.write`). Network access is a separate allowlist of https origins
  (`permissions.network`), reached only through `net.fetch`. The user grants scopes and origins per
  project at install time; ungranted calls are refused with a typed error.
- **Untrusted by design**: the host validates every request, the server re-verifies every
  attributed call (`sol.ask`, `storage.*`), and a team owner can block an extension team-wide. Your
  code cannot widen its own permissions.

## Bundle layout

```
my-extension/
├── extension.toml        # required, at the root (not inside a wrapper folder)
├── widget.html           # views.widget.entry
├── page.html             # views.page.entry
├── window.html           # views.window.entry
├── icon.svg              # views.page.icon — monochrome, path-only, ≤ 16 KiB
├── bridge.js             # your postMessage client (see Getting started)
├── app.js / style.css    # anything you like, bundle-relative
├── OVERVIEW.md           # store.overview — required, ≤ 32 KiB
├── PRIVACY.md            # store.privacy_policy — required once you declare any permission
├── docs/HOW.md           # [[store.sections]] bodies, ≤ 16 KiB each
└── shots/table.png       # store.screenshots — .png/.webp, ≤ 1 MiB each, ≤ 6
```

Allowed file types anywhere in the bundle: `.html .js .css .json .svg .png .webp .woff2 .md .toml`.
Anything else (`.wasm`, `.map`, `.DS_Store`, …) fails review. Whole bundle ≤ 25 MiB uncompressed.

## Lifecycle

1. **Author** the bundle. Only `extension.toml` is mandatory beyond your entry files and
   `OVERVIEW.md`.
2. **Validate in developer mode** — Settings → Developer → _Load unpacked extension…_ Solus parses
   the manifest with the same contract the server uses and shows the same dotted-path problems.
   The extension then runs with a `DEV` badge; grants are session-local. (Developer mode checks the
   manifest only — the static content checks run at publish.)
3. **Publish** — `POST /api/v1/extensions/publish` with the zip. The request validates the whole
   bundle synchronously and answers `202` with a `pending` version.
4. **Automated review** — a background job re-runs the validator, sanitizes the icon, extracts the
   store assets, and sets the version `approved` (visible in the catalog) or `rejected` (problems
   listed on the review route, visible only to you).
5. **Install per project** — a project member picks a version, sees the permissions step (scopes,
   origins, your privacy policy), grants, and installs. Installs pin a version; updates are an
   explicit user action, and a version that widens permissions re-asks.

## Conventions used in these pages

- Sizes are binary: 1 KiB = 1024 bytes, 1 MiB = 1024 KiB.
- "Refused" means the bridge answered `{ ok: false, error }`; "dropped" means no answer at all.
- `<id>` is the manifest's `extension.id` (also called the slug); `<version>` is its semver.
