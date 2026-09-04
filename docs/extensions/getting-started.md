# Getting started — a "Hello" widget

This walkthrough builds a widget that greets whatever entity the user has focused, loads it in
developer mode, then adds a page view (with a rail icon) and a window view. Every file is shown in
full. Reference pages: [manifest](manifest.md), [bridge API](bridge-api.md),
[publishing](publishing.md).

## 1. Files

```
hello-widget/
├── extension.toml
├── widget.html
├── style.css
├── bridge.js
├── app.js
└── OVERVIEW.md
```

### `extension.toml`

```toml
schema_version = 1

[extension]
id = "hello-widget"                  # lowercase slug, 2–64 chars; also the folder name Solus caches under
name = "Hello"
version = "0.1.0"
publisher = "Your name"
summary = "Greets whatever is focused."

[views]
widget = { entry = "widget.html", preferred = "compact" }

[store]
overview = "OVERVIEW.md"
```

No `[permissions]` block yet — the widget only needs what every frame gets for free (the `init`
payload and the unscoped methods). Because it declares no scopes and no network origins, no privacy
policy is required.

### `widget.html`

```html
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <link rel="stylesheet" href="style.css" />
  </head>
  <body>
    <p id="out" role="status">Starting…</p>
    <script src="bridge.js"></script>
    <script src="app.js"></script>
  </body>
</html>
```

Two rules the frame's CSP imposes (see [bridge API → CSP](bridge-api.md#the-csp-you-run-under)):
scripts must be bundle files (`<script src="…">` — an inline `<script>` block never runs), and every
`href`/`src` must be bundle-relative (no `https:`, `//`, `javascript:`). The publish validator
rejects remote references; the CSP blocks them at runtime regardless.

### `style.css`

The host sends its theme as CSS variables (`--bg`, `--sur`, `--tx`, `--mut`, `--acc`, …). Apply
them to `:root` and use them so the widget follows the user's theme.

```css
:root {
  color-scheme: light dark;
}
body {
  margin: 0;
  padding: 8px 12px;
  font:
    13px/1.4 system-ui,
    sans-serif;
  background: var(--bg, #111);
  color: var(--tx, #eee);
}
.muted {
  color: var(--mut, #888);
}
```

### `bridge.js`

A ~40-line `postMessage` client. Copy it into every bundle; it is not something Solus injects.

```js
// bridge.js — minimal Solus bridge client (protocol v1).
(function () {
  const pending = new Map();
  const listeners = new Map();
  let counter = 0;
  let resolveInit;
  const initPromise = new Promise((r) => (resolveInit = r));

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const msg = event.data;
    if (!msg || msg.v !== 1) return;
    if (typeof msg.event === "string") {
      if (msg.event === "init") resolveInit(msg.data);
      for (const fn of listeners.get(msg.event) || []) fn(msg.data);
      return;
    }
    const entry = pending.get(msg.id);
    if (!entry) return;
    pending.delete(msg.id);
    if (msg.ok) entry.resolve(msg.result);
    else
      entry.reject(
        Object.assign(new Error(msg.error.message), { code: msg.error.code }),
      );
  });

  function call(method, params) {
    const id = "r" + ++counter; // [A-Za-z0-9_-], ≤ 64 chars, unique while in flight
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      window.parent.postMessage(
        { v: 1, id, method, params: params || {} },
        "*",
      );
    });
  }

  function on(event, handler) {
    listeners.set(event, [...(listeners.get(event) || []), handler]);
    return () =>
      listeners.set(
        event,
        (listeners.get(event) || []).filter((h) => h !== handler),
      );
  }

  // Waits for `init`, sends `ui.ready`, resolves with the init payload.
  const ready = () =>
    initPromise.then((init) => call("ui.ready").then(() => init));

  window.solus = { call, on, ready };
})();
```

Notes:

- `event.source !== window.parent` — only the host's messages are accepted.
- `postMessage(…, '*')` — the frame has an opaque origin and cannot name the host's; the host
  accepts messages only from the frame it mounted, so nothing else can receive yours.
- `ready()` must be called within **10 s** of the frame loading, or the host shows "didn't start".
- Do not write the tokens `fetch(`, `XMLHttpRequest`, `WebSocket(`, `EventSource(`,
  `sendBeacon(`, `new Worker(`, `importScripts(` or `navigator.serviceWorker` anywhere in your JS —
  not even in comments. The static check is textual and rejects the bundle at publish.

### `app.js`

```js
const out = document.getElementById("out");

function applyTheme(vars) {
  for (const [name, value] of Object.entries(vars)) {
    document.documentElement.style.setProperty(name, value);
  }
}

function render(focus) {
  if (!focus) {
    out.textContent = "Hello — nothing is focused yet.";
    out.className = "muted";
    return;
  }
  out.textContent = `Hello, ${focus.label ?? focus.entity.entityId} (${focus.domain})`;
  out.className = "";
}

solus.ready().then((init) => {
  applyTheme(init.theme);
  render(init.focus);
});
solus.on("theme.changed", applyTheme);
solus.on("focus.changed", render); // delivered only once you hold focus.read or graph.read — step 3
```

`init` carries the current focus even without a scope. Live `focus.changed` events, and
`focus.get`, need `focus.read` (or `graph.read`) — added in step 3.

### `OVERVIEW.md`

```markdown
# Hello

Greets the entity you have focused. A worked example from the Solus extension docs.
```

Markdown shown in the Store is rendered as text-safe Markdown: no `<script`, `<iframe`,
`javascript:` links or `on*=` attributes (the validator rejects them).

## 2. Load it in developer mode

1. Open **Settings → Developer**.
2. Click **Load unpacked extension…** and pick the `hello-widget` folder. Solus refuses your home
   folder (or any ancestor of it), a filesystem root, and anything under `~/.solus`.
3. Solus reads `extension.toml` (≤ 64 KiB) and validates it with the manifest contract. Problems
   are listed as dotted paths (`views.widget.entry: must be a relative path inside the bundle ending
in .html`) — identical to what the publish validator would say. Fix and **Pick again**.
4. On success the permissions step appears (titled with a `DEV` badge). Grant what the manifest
   declares — nothing, for now.
5. Open a project's Live Bench and add the widget from the picker under **Developer (this
   session)**.

**Reload** re-validates the manifest and remounts every frame of the extension with a fresh
cache-busting nonce, so edits to any file show up on the next Reload. **Remove** forgets the
registration. The registration is written to `~/.solus/extensions/index.json` (source `dev` plus your
folder path) and re-validated every time a file is served.

### What the `DEV` badge means

| Aspect              | Dev registration                                                                                                           |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| URL                 | `solus-ext://<id>/dev/<path>` — the literal version `dev`, served straight from your folder                                |
| `init.version`      | `"dev"`; `init.mode` is `"dev"` for every view kind (widget, page, window)                                                 |
| Grants              | Session-local, never sent to the server, never merged with a published install of the same id                              |
| Server-backed calls | `sol.ask`, `findings.create`, `storage.get/set/delete` answer `blocked` — there is no install row for the server to verify |
| Integrity           | No content-hash check (nothing to compare against)                                                                         |
| Validation          | Manifest only. The publish-time static checks (remote references, `fetch(`, disallowed file types) do **not** run here     |
| Tooltip             | Hover the badge (page header, slot chrome, window) to see the registered path and how many malformed messages were dropped |
| Publishing          | Not offered from the desktop — see [publishing](publishing.md)                                                             |

A published extension with the same id installed in the project appears alongside the dev one; the
badge tells them apart.

## 3. Ask for a scope (and add a privacy policy)

To receive `focus.changed` and call `focus.get`, declare `focus.read`. Declaring **any** scope or
network origin makes `store.privacy_policy` mandatory.

```toml
[permissions]
scopes = ["focus.read"]

[store]
overview = "OVERVIEW.md"
privacy_policy = "PRIVACY.md"
```

`PRIVACY.md` (Markdown, ≤ 32 KiB) is shown in the permissions step. Say what the extension reads
and where, if anywhere, data goes — for this widget: "Reads the focused entity's id, name and
domain. Nothing leaves Solus." Reload in Settings → Developer; the permissions step shows the new
scope, and `focus.changed` starts arriving.

## 4. Add a page view with an icon

```toml
[views]
widget = { entry = "widget.html", preferred = "compact" }
page = { entry = "page.html", icon = "icon.svg", label = "Hello" }   # label ≤ 24 chars
```

`page.html` can be the same shape as `widget.html` (bigger layout, same `bridge.js`). The page
appears in the rail with your icon and label; its header carries the version, publisher and the
`DEV` badge.

### Icon rules

The icon is the one piece of your markup the host renders **outside** the sandbox, so it is
reduced to a strict subset before it touches the DOM — at publish (stored reduced) and again on the
desktop. An icon that fails is replaced by a blank tile, and at publish it rejects the bundle.

- File: `.svg`, ≤ **16 KiB**, well-formed XML, root element `<svg>`, `xmlns` (if present) exactly
  `http://www.w3.org/2000/svg`. No DOCTYPE, no entities, no processing instructions (omit the
  `<?xml …?>` declaration).
- Elements: `svg g path circle rect line polyline polygon ellipse title` — nothing else. No
  `<defs>`, `<use>`, `<style>`, `<script>`, `<image>`, `<text>`, `<foreignObject>`.
- Attributes: `d cx cy r rx ry x y x1 y1 x2 y2 width height viewBox points fill stroke stroke-width
stroke-linecap stroke-linejoin fill-rule opacity transform xmlns`. No `id`, `class`, `style`,
  `href`, and no `on*` handlers.
- Colours: `fill`/`stroke` must be `none`, `currentColor`, a hex colour or a colour name (no
  `url(…)`, no `rgb(…)`). Every colour other than `none` is rewritten to **`currentColor`**, so
  draw for one colour — the icon takes the rail's text colour in both themes.
- Text is kept only inside `<title>`; comments are dropped.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <title>Hello</title>
  <circle cx="8" cy="8" r="6.5"/>
  <path d="M5.5 9.5c.7 1 1.5 1.5 2.5 1.5s1.8-.5 2.5-1.5M6 6.5h.01M10 6.5h.01"/>
</svg>
```

Draw on a 16×16 (or 24×24) `viewBox`; the rail renders it at 16 px.

## 5. Add a window view

```toml
[views]
widget = { entry = "widget.html", preferred = "compact" }
page = { entry = "page.html", icon = "icon.svg", label = "Hello" }
window = { entry = "window.html", title = "Hello", width = 640, height = 480 }
```

- `title` (≤ 60 chars) is the OS window title. It is sanitized by Solus; a `<title>` inside
  `window.html` is ignored.
- `width`/`height` are optional integers, 320–4096 px, defaulting to 960×640.
- The window is opened from the page header's **Open in window** action; it hosts the same
  sandboxed frame with the same bridge and grants. On a project switch the window receives
  `project.changed` and is then remounted — treat it as a full reset.

## 6. Next steps

- Read a graph entity: declare `graph.read` and call `graph.getEntity` / `graph.search` — see
  [bridge API](bridge-api.md#methods).
- Remember something per project: declare `storage.own` and use `storage.set` / `storage.get`
  (published installs only; dev mode answers `blocked`).
- Call an external API: list its https origin in `permissions.network` and use `net.fetch`.
- When it works, [package and publish](publishing.md).
