# COWORK_QA — Extensions (SOLUSDEV-235, end to end)

End-to-end test plan for the extension SYSTEM in Solus: publishing to the registry, the
server-backed Store, the install/grant/update lifecycle, the sandboxed runtime (widget canvas,
page view, window view), developer mode, team policy, and the host bridge. Written for a tester
with the running app, a terminal, and this file only. `COWORK_QA_store.md` stays the Store-only
plan; this file covers everything around it.

Governing docs (for reference, not required reading): `docs/api/extensions.md` (routes, error
codes), `docs/wireflows/store.md`, `docs/wireflows/extensions-runtime.md`,
`docs/wireflows/widget-canvas.md`, `docs/architecture/extensions-runtime.md`,
`docs/contracts/extension-manifest.md`.

## Scope of this build

What is real:

- Installs, enablement, settings values, permission grants, team policies and the Live Bench
  widget layout all live on the server (`/api/v1/...`). Nothing extension-related persists in
  the desktop's local storage; the desktop re-reads install rows every 10 s.
- Bundles are downloaded by the desktop, hash-verified, and cached under
  `~/.solus/extensions/<id>/<version>/`, with `~/.solus/extensions/index.json` as the cache
  index. Extension code runs only inside a sandboxed iframe served from `solus-ext://`.
- Publishing is open to any signed-in user with a verified email, **via the API only** — there
  is no in-app publish UI. `+ Create extension` in the Store opens an explanatory dialog.
- The `verified` badge is a Solus-staff flag set with `PATCH /extensions/{slug}` by a user id
  listed in `SOLUS_STAFF_USER_IDS`.
- Developer mode (Settings → Developer) loads an unpacked folder, validates it with the same
  contract as the publish path, and shows a `DEV` badge. Dev extensions never publish.

What is NOT in this build (expected, not defects):

- "SOL grounding" is mentioned in the Create-extension dialog copy but is not a declarable view;
  nothing grounds SOL from an extension.
- No credit meter per extension: the Overview CREDITS card always reads `This cycle —`.
- No `▾ More` rail overflow: the rail shows at most 8 extension page entries; the rest stay
  reachable from the Store.
- The `View` menu has no entries for extension pages.
- Developer registrations do NOT get their own rail entry or picker row. A dev registration is
  rendered wherever a frame for the same extension id would mount — i.e. load the unpacked
  folder of an extension that is also installed in the project, and the dev copy takes over its
  widget/page/window with the `DEV` badge (this is how §1 and §10 below exercise it).
- Dev registrations are remembered across restarts (they are recorded in `index.json` and
  re-validated on launch) — the wireflow's "forgotten when Solus quits" is not what shipped.
- The extension window is not closed automatically on sign-out.
- Review `rejected` is practically unreachable through the API: the same bundle checks run in
  the upload request (`422 bundle_invalid`), so the review job only ever sees bundles that
  already passed them.

## Required setup

### Services

1. Postgres and Redis running (`make db-up`). Start the API from the repo root with, at least:

   ```bash
   SOLUS_SUPABASE_JWT_SECRET=dummy-dev-signing-value \
   SOLUS_REDIS_URL=redis://localhost:6379/0 \
   SOLUS_STAFF_USER_IDS=99999999-9999-9999-9999-999999999999 \
   uv run uvicorn --factory solus_api.main:create_app --port 8000
   ```

   (see `docs/api/API-implementation.md` §1 for the DB bootstrap). Export
   `A=http://localhost:8000/api/v1`.

2. Start the ARQ worker in a second terminal — the publish review job runs there:
   `uv run arq solus_api.worker_main.WorkerSettings`. Without it every published version stays
   `pending` forever (§2.3 checks exactly that).
3. Solus desktop app running against this API (`make dev-desktop`), signed in, onboarding done.
   The account the desktop is signed in with is **ALICE** below.

### Users and tokens

Mint dev JWTs with the snippet in `docs/api/API-implementation.md` §1 ("Minting a dev JWT").
Any token signed with `SOLUS_SUPABASE_JWT_SECRET` whose `sub` matches an existing user IS that
user, so:

| var       | who                               | `sub`                                                                                                                       | notes                                                                                            |
| --------- | --------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `$ALICE`  | the desktop user; owner of team A | the desktop user's id — read it with `curl -s $A/users/me -H "Authorization: Bearer <desktop token>"` or Settings → Profile | all desktop flows run as her                                                                     |
| `$BOB`    | owner of team B; second publisher | any new UUID                                                                                                                | isolation checks; `slug_taken`                                                                   |
| `$CAROL`  | admin of team A                   | any new UUID                                                                                                                | invite her: `POST $A/teams/{A}/invites {"email":"carol@example.com","role":"admin"}` then accept |
| `$VIEWER` | viewer of team A                  | any new UUID                                                                                                                | same invite flow with `"role":"viewer"`                                                          |
| `$PUB`    | the publisher                     | any new UUID, `email_verified` claim absent or `true`                                                                       | owns `hello-widget` and `hello-probe`                                                            |
| `$PUBX`   | the publisher, unverified         | same `sub` as `$PUB`, claim `'email_verified': False`                                                                       | §2.9                                                                                             |
| `$STAFF`  | Solus staff                       | `99999999-9999-9999-9999-999999999999` (the id in `SOLUS_STAFF_USER_IDS`)                                                   | §3.4                                                                                             |

Invite acceptance: `POST $A/invites/{token}/accept` as the invitee (the token is in the invite
response). First authenticated request auto-provisions each user.

### Projects

- **Team A** (ALICE's team): **Project A** with a KiCad source connected (Sources → Connect a
  tool → KiCad, committed export) — needed for the EDA-gated extension; **Project A2** with no
  sources.
- **Team B** (BOB's team): **Project B**.
- Export the ids as `$PA`, `$PA2`, `$PB`, and the team ids as `$TA`, `$TB` (`GET $A/teams`,
  `GET $A/teams/{id}/projects`).

### Fixture extensions (make these by hand)

Every bundle file must be at the zip ROOT (zip the folder's contents, not the folder). The
sandbox CSP forbids inline `<script>` and `<style>`, so the script lives in `widget.js`.

**`hello-widget/`** — the smallest valid extension, no permissions.

`hello-widget/extension.toml`

```toml
schema_version = 1

[extension]
id = "hello-widget"
name = "Hello Widget"
version = "0.1.0"
publisher = "QA Lab"
summary = "The smallest valid extension: one widget, no permissions."
requires = []

[views]
widget = { entry = "index.html", preferred = "compact" }

[store]
overview = "OVERVIEW.md"
```

`hello-widget/OVERVIEW.md`

```markdown
# Hello Widget

A one-file widget used to test the Solus extension system.
```

`hello-widget/index.html` (identical in every fixture)

```html
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Hello</title>
  </head>
  <body>
    <h1>Hello from <span id="mode">…</span></h1>
    <div id="buttons"></div>
    <pre id="log"></pre>
    <script src="widget.js"></script>
  </body>
</html>
```

`hello-widget/widget.js` (identical in every fixture — a minimal bridge client)

```js
// Solus bridge client: postMessage { v:1, id, method, params } to the host; log every answer.
const log = document.getElementById("log");
const pending = new Map();
let seq = 0;
function call(method, params = {}) {
  const id = "r" + ++seq;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    window.parent.postMessage({ v: 1, id, method, params }, "*");
  });
}
function show(label, value) {
  log.textContent =
    label + " → " + JSON.stringify(value) + "\n" + log.textContent;
}
window.addEventListener("message", (e) => {
  const m = e.data;
  if (!m || m.v !== 1) return;
  if (m.event) {
    if (m.event === "init") {
      document.getElementById("mode").textContent =
        m.data.mode + " · " + m.data.version;
      call("ui.ready").then(() => show("ui.ready", "ok"));
    }
    show("event " + m.event, m.data);
    return;
  }
  const resolve = pending.get(m.id);
  if (resolve) {
    pending.delete(m.id);
    resolve(m.ok ? m.result : { error: m.error });
  }
});
const ACTIONS = {
  focus: () => call("graph.getFocus"),
  "storage-set": () =>
    call("storage.set", { key: "greeting", value: "hi " + Date.now() }),
  "storage-get": () => call("storage.get", { key: "greeting" }),
  "fetch-ok": () =>
    call("net.fetch", { url: "https://example.com/", method: "GET" }),
  "fetch-denied": () =>
    call("net.fetch", { url: "https://example.org/", method: "GET" }),
  sol: () =>
    call("sol.ask", {
      prompt: "In one sentence, what is this project?",
      entityIds: [],
    }),
  unknown: () => call("graph.dropTables"),
  "bad-params": () => call("graph.getFocus", { projectId: "p1" }),
  burst: () =>
    Promise.all(Array.from({ length: 70 }, () => call("settings.get"))).then(
      (rs) => ({
        total: rs.length,
        rate_limited: rs.filter(
          (r) => r.error && r.error.code === "rate_limited",
        ).length,
      }),
    ),
};
for (const [key, run] of Object.entries(ACTIONS)) {
  const b = document.createElement("button");
  b.textContent = key;
  b.onclick = () => run().then((r) => show(key, r));
  document.getElementById("buttons").appendChild(b);
}
```

**`hello-probe/`** — declares permissions, settings, all three views, and an EDA requirement.
Copy `index.html`, `widget.js` and `OVERVIEW.md` from `hello-widget/` (fix the title), then:

`hello-probe/extension.toml`

```toml
schema_version = 1

[extension]
id = "hello-probe"
name = "Hello Probe"
version = "1.0.0"
publisher = "QA Lab"
summary = "Exercises the host bridge: focus, storage, network, SOL."
requires = [["eda"]]

[views]
widget = { entry = "index.html", preferred = "standard", minimum = "standard" }
page = { entry = "index.html", icon = "icon.svg", label = "Probe" }
window = { entry = "index.html", title = "Probe window", width = 720, height = 480 }

[permissions]
scopes = ["graph.read", "storage.own", "sol.ask"]
network = ["https://example.com"]

[settings]
[[settings.fields]]
key = "verbose"
type = "boolean"
label = "Verbose logging"
default = false

[[settings.fields]]
key = "refresh"
type = "select"
label = "Run frequency"
options = ["every_sync", "hourly", "daily"]
default = "every_sync"

[[settings.fields]]
key = "limit"
type = "number"
label = "Row limit"
default = 10
min = 1
max = 50

[[settings.fields]]
key = "label"
type = "string"
label = "Panel label"
default = "Probe"

[store]
overview = "OVERVIEW.md"
privacy_policy = "PRIVACY.md"
links = { documentation = "https://example.com/docs", issues = "https://example.com/issues" }
```

`hello-probe/PRIVACY.md`

```markdown
# Privacy

Hello Probe stores one greeting string in its own per-project storage and fetches
https://example.com/ when you press a button. It sends nothing anywhere else.
```

`hello-probe/icon.svg`

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4 4h16v16H4z"/></svg>
```

**Update fixtures for §8** (copies of `hello-probe/` with only `extension.toml` changed):

- `hello-probe-1.1.0/`: `version = "1.1.0"`, `summary = "… (1.1.0)"`, everything else identical.
- `hello-probe-1.2.0/`: `version = "1.2.0"` and
  `scopes = ["graph.read", "storage.own", "sol.ask", "telemetry.read"]`.

**Broken fixture for §1**: `broken-ext/` = a copy of `hello-widget/` whose `extension.toml` has
`widget = { entry = "../index.html", preferred = "compact" }` and an extra line
`postinstall = "rm -rf /"` under `[extension]`.

Zips (from inside each folder): `cd hello-widget && zip -r ../hello-widget-0.1.0.zip . && cd ..`,
likewise `hello-probe-1.0.0.zip`, `hello-probe-1.1.0.zip`, `hello-probe-1.2.0.zip`.

Publish shorthand used below:

```bash
pub() { curl -s -o /tmp/pub.json -w '%{http_code}\n' -X POST "$A/extensions/publish" \
  -H "Authorization: Bearer ${2:-$PUB}" -H "Idempotency-Key: $3" \
  -F "bundle=@$1;type=application/zip"; cat /tmp/pub.json; echo; }
# usage: pub hello-widget-0.1.0.zip "$PUB" key-hw-010
```

## 1. Developer mode (Settings → Developer)

| #    | Step                                                                                      | Expected                                                                                                                                                                                                                                                                 | Pass |
| ---- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---- |
| 1.1  | Open Settings (rail gear). Scroll below Integrations.                                     | Section **Developer** with sub "Load an unpacked extension folder to test it in this project. Dev extensions never publish and show a DEV badge everywhere.", a **Load unpacked extension…** button, and "No unpacked extensions loaded."                                | ☐    |
| 1.2  | Click **Load unpacked extension…**, pick your home folder.                                | Red note under the button: `<path> — not loaded` with one problem line: "path: must be an existing directory that is not the filesystem root, your home folder (or an ancestor of it), or ~/.solus". Nothing is listed.                                                  | ☐    |
| 1.3  | Load `~/.solus/extensions` (or `/`).                                                      | Same refusal text.                                                                                                                                                                                                                                                       | ☐    |
| 1.4  | Load an empty folder.                                                                     | Problem "extension.toml: missing (must be a regular file at the folder root)".                                                                                                                                                                                           | ☐    |
| 1.5  | Load `broken-ext/`.                                                                       | Not loaded; problems are the contract's dotted-path strings, one per line, e.g. `views.widget.entry: …` (traversal) and `extension.postinstall: …` (unknown field). Exact wording is whatever the validator says — the same strings a publish would return in `details`. | ☐    |
| 1.6  | Fix `broken-ext/extension.toml` (remove `postinstall`, restore the entry), load it again. | Row appears: name **Hello Widget**, `DEV` badge, mono `hello-widget`, the folder path, buttons **Reload** and **Remove**. No permissions step appears (dev grants are automatic for the session).                                                                        | ☐    |
| 1.7  | Hover the `DEV` badge.                                                                    | Tooltip "Developer registration — loaded from a folder on this computer".                                                                                                                                                                                                | ☐    |
| 1.8  | Edit `extension.toml` to a broken value again, click **Reload**.                          | The row stays (name still shown) with the new problem list under it in red; **Reload** remains.                                                                                                                                                                          | ☐    |
| 1.9  | Fix the file, **Reload**.                                                                 | Problems disappear.                                                                                                                                                                                                                                                      | ☐    |
| 1.10 | Set `schema_version = 2`, **Reload**.                                                     | Listed with a problem naming the newer schema (not loaded). Restore `schema_version = 1`.                                                                                                                                                                                | ☐    |
| 1.11 | Quit and relaunch Solus, open Settings.                                                   | The registration is still listed (re-validated on launch).                                                                                                                                                                                                               | ☐    |
| 1.12 | Click **Remove**.                                                                         | Row disappears; "No unpacked extensions loaded." returns. `~/.solus/extensions/index.json` no longer has a `hello-widget` entry with `"source": "dev"`.                                                                                                                  | ☐    |
| 1.13 | Where does a dev extension render?                                                        | Nowhere yet: the rail and the widget picker list server installs only. §10 loads a dev folder for an extension that is ALSO installed, which makes the dev copy take over that extension's frames.                                                                       | ☐    |

## 2. Publish via curl

| #    | Step                                                                                                                                                        | Expected                                                                                                                                                                                                                                       | Pass |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 2.1  | `pub hello-widget-0.1.0.zip "$PUB" key-hw-010`                                                                                                              | `202`; body `data.version` = `{slug:"hello-widget", version:"0.1.0", review_status:"pending", content_hash, bundle_size_bytes, bundle_url, review_url, created_at}` and `data.review = {status:"pending", problems:[]}`. No `Location` header. | ☐    |
| 2.2  | Poll `curl -s $A/extensions/hello-widget/versions/0.1.0/review -H "Authorization: Bearer $PUB"` every second.                                               | `200`; `review_status` goes `pending` → (`checking`) → `approved` within a few seconds; `review_problems: []`; `published_at` set.                                                                                                             | ☐    |
| 2.3  | Stop the ARQ worker. `pub hello-probe-1.0.0.zip "$PUB" key-hp-100`. Poll the review for 20 s. Start the worker.                                             | Stays `pending` while the worker is down; becomes `approved` shortly after the worker starts.                                                                                                                                                  | ☐    |
| 2.4  | Same review URL as `$BOB` and as `$ALICE`.                                                                                                                  | `404 not_found` for both (a review you did not publish does not exist for you).                                                                                                                                                                | ☐    |
| 2.5  | Replay: `pub hello-widget-0.1.0.zip "$PUB" key-hw-010` (same key, same bytes).                                                                              | `202` with the SAME body as 2.1 (no new version).                                                                                                                                                                                              | ☐    |
| 2.6  | Conflict: `pub hello-probe-1.0.0.zip "$PUB" key-hw-010` (same key, different bytes).                                                                        | `409 idempotency_conflict`.                                                                                                                                                                                                                    | ☐    |
| 2.7  | No key: `curl -s -w '%{http_code}' -X POST $A/extensions/publish -H "Authorization: Bearer $PUB" -F "bundle=@hello-widget-0.1.0.zip;type=application/zip"`. | `400 idempotency_key_required`.                                                                                                                                                                                                                | ☐    |
| 2.8  | `version_exists`: `pub hello-widget-0.1.0.zip "$PUB" key-hw-010-again`.                                                                                     | `409 version_exists`.                                                                                                                                                                                                                          | ☐    |
| 2.9  | Unverified email: `pub hello-widget-0.1.0.zip "$PUBX" key-x`.                                                                                               | `403 email_not_verified`.                                                                                                                                                                                                                      | ☐    |
| 2.10 | `slug_taken`: `pub hello-widget-0.1.0.zip "$BOB" key-bob-1`.                                                                                                | `409 slug_taken`.                                                                                                                                                                                                                              | ☐    |
| 2.11 | Bad bundle: add `helper.wasm` (any bytes) to a copy of `hello-widget/`, zip, publish with a new key.                                                        | `422 bundle_invalid`; `error.details` contains `helper.wasm: not an allowed file type (.html, .js, .css, .json, .svg, .png, .webp, .woff2, .md, .toml)`.                                                                                       | ☐    |
| 2.12 | Zip the FOLDER instead of its contents (`zip -r wrong.zip hello-widget`), publish.                                                                          | `422 bundle_invalid`; details: "extension.toml: must be at the bundle root, found inside 'hello-widget/' — zip the folder's contents, not the folder".                                                                                         | ☐    |
| 2.13 | Publish `broken-ext/` zipped (the §1.5 state).                                                                                                              | `422 bundle_invalid`; details are the SAME dotted-path strings developer mode showed in 1.5.                                                                                                                                                   | ☐    |
| 2.14 | 413: `dd if=/dev/urandom of=big.zip bs=1m count=26` then `pub big.zip "$PUB" key-big`.                                                                      | `413 payload_too_large` (refused before the body is read).                                                                                                                                                                                     | ☐    |
| 2.15 | Extra form field: add `-F name=x` to a publish.                                                                                                             | `422 validation_error` "Unknown field(s): name".                                                                                                                                                                                               | ☐    |
| 2.16 | `GET $A/extensions/hello-widget/versions` as `$PUB`, then as `$BOB`.                                                                                        | Both `200`; the publisher's view would additionally list pending/rejected versions with `review_problems`; BOB sees approved ones only.                                                                                                        | ☐    |
| 2.17 | Bundle bytes: `curl -sI $A/extensions/hello-widget/versions/0.1.0/bundle -H "Authorization: Bearer $BOB"`.                                                  | `200`, `Content-Type: application/zip`, `X-Solus-Content-Hash` = the `content_hash` from 2.1.                                                                                                                                                  | ☐    |
| 2.18 | Assets: `GET …/versions/1.0.0/assets/OVERVIEW.md` for hello-probe, then `…/assets/widget.js`, then `…/assets/../extension.toml`.                            | `200 text/markdown`; `404 not_found`; `404`/`422` (only files named by `[store]` and the page icon are served).                                                                                                                                | ☐    |
| 2.19 | (Optional) Publish 11 versions of a throwaway id within an hour.                                                                                            | The 11th is `429 rate_limited` with `Retry-After`.                                                                                                                                                                                             | ☐    |

## 3. Store catalog from the server

| #   | Step                                                                                                                                                   | Expected                                                                                                                                                                                                                                                                                      | Pass |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 3.1 | `curl -s $A/extensions -H "Authorization: Bearer $BOB"`                                                                                                | `200`; `data` lists `hello-probe` and `hello-widget` (name order) with `verified:false`, `install_count:0`, `latest_version`, `requires` (`[["eda"]]` / `[]`), `views`. Nothing pending appears (publish a `hello-pending` 0.0.1 with the worker stopped to prove it, then start the worker). | ☐    |
| 3.2 | Desktop: Project A open → rail `+` (Store).                                                                                                            | Header **Store** + subtitle; INSTALLED reads "Nothing installed in this project yet."; POPULAR EXTENSIONS shows **Hello Probe** and **Hello Widget**, both with a muted `COMMUNITY` badge; Hello Widget `AVAILABLE`; Hello Probe `AVAILABLE` (KiCad connected).                               | ☐    |
| 3.3 | Switch to Project A2 (no sources).                                                                                                                     | Hello Probe now shows `NEEDS EDA`; Hello Widget still `AVAILABLE`.                                                                                                                                                                                                                            | ☐    |
| 3.4 | Staff badge: `curl -s -X PATCH $A/extensions/hello-probe -H "Authorization: Bearer $STAFF" -H 'Content-Type: application/json' -d '{"verified":true}'` | `200`, detail body with `verified:true`. Within 10 s (or on re-opening the Store) the Hello Probe badge becomes `QA LAB ✓` in green (tooltip "Verified by Solus").                                                                                                                            | ☐    |
| 3.5 | Same PATCH as `$PUB` (the owner) and as `$ALICE`.                                                                                                      | `403 forbidden` for both; response never says who is staff.                                                                                                                                                                                                                                   | ☐    |
| 3.6 | PATCH as `$STAFF` with `{"verified":true,"name":"x"}`.                                                                                                 | `422 validation_error`.                                                                                                                                                                                                                                                                       | ☐    |
| 3.7 | Stop the API, reload the Store (rail `+`).                                                                                                             | Note "Solus can't reach the Store right now, so nothing can be installed and source requirements are shown as unmet."; POPULAR reads "The catalog is unavailable while Solus is offline." No stale cards. Start the API.                                                                      | ☐    |

## 4. Install with the permissions step

| #    | Step                                                                                                                           | Expected                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Pass |
| ---- | ------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 4.1  | Project A → Store → click **Hello Widget**.                                                                                    | Detail: `← Store`, icon tile, **Hello Widget**, `COMMUNITY`, meta `QA Lab · v0.1.0 · 0 installs · updated <n>m ago`; **Install** (enabled). Overview → WHAT IT ADDS: "Widget" and "Permissions / Asks for nothing"; IN THIS PROJECT `NOT INSTALLED` "Install to see its activity here."; REQUIRES "No connected source required."; CREDITS `This cycle —`; LINKS "No links published."                                                                                                                                                                                                                                            | ☐    |
| 4.2  | Click **Install**.                                                                                                             | Modal, mono title `INSTALL HELLO WIDGET`, `v0.1.0`, ✕; "by COMMUNITY"; body "Hello Widget asks for nothing. It runs entirely inside its sandbox."; buttons **Cancel** / **Install**.                                                                                                                                                                                                                                                                                                                                                                                                                                              | ☐    |
| 4.3  | Press Escape. Reopen, click ✕. Reopen, click **Cancel**.                                                                       | Modal closes each time. `curl -s $A/projects/$PA/extensions -H "Authorization: Bearer $ALICE"` → `data: []` (nothing created).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | ☐    |
| 4.4  | **Install** → **Install**.                                                                                                     | Button reads "Installing…" briefly; modal closes; header now **Disable** / **Uninstall**; IN THIS PROJECT `IDLE` "No activity in this project yet."; no error line.                                                                                                                                                                                                                                                                                                                                                                                                                                                               | ☐    |
| 4.5  | Check the machine.                                                                                                             | `~/.solus/extensions/hello-widget/0.1.0/` contains `extension.toml`, `index.html`, `widget.js`, `OVERVIEW.md`; `~/.solus/extensions/index.json` has `installed["hello-widget"] = { version:"0.1.0", contentHash:<2.1 hash>, installedAt, source:"registry" }`.                                                                                                                                                                                                                                                                                                                                                                    | ☐    |
| 4.6  | Server: `GET $A/projects/$PA/extensions` as ALICE.                                                                             | One row: `extension.slug hello-widget`, `version.version 0.1.0`, `enabled true`, `settings {}`, `granted_scopes []`, `granted_network []`, `update_available null`, `policy {blocked:false,…}`, `installed_by` = ALICE's id.                                                                                                                                                                                                                                                                                                                                                                                                      | ☐    |
| 4.7  | Back to the catalog.                                                                                                           | Hello Widget under INSTALLED with `● INSTALLED`; meta on its detail now `1 installs` (the catalog aggregate; the label is not singularised in this build).                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | ☐    |
| 4.8  | Open **Hello Probe** → **Install**.                                                                                            | Modal `INSTALL HELLO PROBE` `v1.0.0`, "by QA LAB ✓". "Hello Probe asks for" with three rows: "Read the context model / graph.read / Entities, relations and neighbourhoods of this project.", "Keep its own data / storage.own / A private per-project key-value store, up to 256 KiB.", "Ask SOL / sol.ask / Metered to your credits and attributed to the extension."; "It may connect to" `https://example.com` (text, not a link); "Nothing else. Solus performs every call on its behalf with your account; the extension never receives your credentials."; **Privacy policy ↗** link; **Cancel** / **Grant and install**. | ☐    |
| 4.9  | Click **Privacy policy ↗**.                                                                                                   | Opens the `PRIVACY.md` asset URL in the system browser (it is behind bearer auth, so the browser may show 401 — the point is that nothing navigates inside Solus).                                                                                                                                                                                                                                                                                                                                                                                                                                                                | ☐    |
| 4.10 | **Grant and install**.                                                                                                         | Installed. Server row: `granted_scopes ["graph.read","sol.ask","storage.own"]`, `granted_network ["https://example.com"]`, `settings {limit:10, label:"Probe", refresh:"every_sync", verbose:false}`. Cache dir `hello-probe/1.0.0/` includes `icon.svg` and `PRIVACY.md`.                                                                                                                                                                                                                                                                                                                                                        | ☐    |
| 4.11 | Switch to Project A2 → Store → Hello Probe.                                                                                    | Header shows mono `NEEDS EDA` and a disabled **Install** (tooltip "Connect a required source first"); REQUIRES row "An EDA source (KiCad, Altium)" with an amber dot.                                                                                                                                                                                                                                                                                                                                                                                                                                                             | ☐    |
| 4.12 | Blocked by team (do §9.1 first, or now): with `hello-widget` blocked, in Project A2 open Hello Widget → Install → **Install**. | Inline red error in the modal "Blocked by your team."; after closing, the header shows "Blocked by your team" and a disabled **Install**; the card reads `BLOCKED`. Unblock (§9.6) before continuing.                                                                                                                                                                                                                                                                                                                                                                                                                             | ☐    |
| 4.13 | Delete `~/.solus/extensions/hello-widget/` by hand, then open Live Bench (with the widget on the canvas, §6).                  | The slot shows "Downloading Hello Widget…" and the bundle is re-downloaded from the install row — nothing but time is lost.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | ☐    |
| 4.14 | Hello Widget → **Uninstall**.                                                                                                  | Dialog "Uninstall Hello Widget?" "Its widgets and checks leave this project. Graph data it already added stays. Your settings are kept if you reinstall." **Cancel** / **Uninstall extension**. Confirm → back to catalog; server row gone (`DELETE` → 204); `~/.solus/extensions/hello-widget/` removed; index entry gone. Reinstall for the flows below.                                                                                                                                                                                                                                                                        | ☐    |

## 5. Page view and window view

| #   | Step                                                                                                                                                    | Expected                                                                                                                                                                                                                                                                                                                                                         | Pass |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 5.1 | Project A open, Hello Probe installed.                                                                                                                  | The rail shows a new entry directly ABOVE the Store `+` (below Team): a square icon drawn in the rail colour (from `icon.svg`), tooltip "Probe". Hello Widget (no page view) has no entry.                                                                                                                                                                       | ☐    |
| 5.2 | Click it.                                                                                                                                               | Screen with header: icon tile, **Hello Probe**, green ✓ (verified), mono `by QA Lab · v1.0.0`; right: **Open in window ↗**. Body: "Loading Hello Probe…" then the frame fades in showing "Hello from page · 1.0.0", the action buttons and a log line `ui.ready → "ok"` plus `event init …`.                                                                    | ☐    |
| 5.3 | Click **Open in window ↗**.                                                                                                                            | A second OS window titled **Probe window**, 720×480, native frame, no menu bar; header inside shows **Probe window** and the frame reports `mode "window"`. Click **Open in window ↗** again → the existing window is focused, not a second one. `Cmd/Ctrl+W` closes it.                                                                                        | ☐    |
| 5.4 | With the window open, switch project in the main window (pill) to A2, then back to A.                                                                   | The main window leaves the page for **Overview** (project switch always leaves an extension page). The window either follows the switch — "hello-probe isn't installed in this project." for A2, recovering on return to A — or keeps A's frame until reopened; it never shows another project's data. (Live follow-through is unconfirmed; note which you saw.) | ☐    |
| 5.5 | `curl -s -X PATCH $A/projects/$PA/extensions/hello-probe -H "Authorization: Bearer $ALICE" -H 'Content-Type: application/json' -d '{"enabled":false}'`  | `200`, `enabled:false`. Within 10 s the rail entry disappears. Store → Hello Probe → Overview reads `DISABLED` "Turned off in this project."; header button **Enable**. Re-enable via the button → rail entry returns.                                                                                                                                           | ☐    |
| 5.6 | Error state: load `hello-probe/` in Settings → Developer, then edit its `extension.toml` page entry to `missing.html`, **Reload**, open the Probe page. | Header shows `DEV` badge and `dev`; body card `ERROR` "Hello Probe didn't start." with detail "It did not respond in 10 s.", the failing request path `solus-ext://hello-probe/dev/missing.html?…`, and buttons **Reload** / **Open in Store**. Restore the entry, **Reload** → renders. **Remove** the dev registration afterwards.                             | ☐    |
| 5.7 | Block Hello Probe team-wide (§9.1 with slug `hello-probe`) while the page is open.                                                                      | Within 10 s the rail entry disappears; opening the extension from the Store detail is no longer possible (`BLOCKED BY TEAM` card). Unblock and re-enable.                                                                                                                                                                                                        | ☐    |
| 5.8 | (Optional) Install 9 page-view extensions.                                                                                                              | The rail shows 8 entries (install order); the 9th is reachable only from the Store.                                                                                                                                                                                                                                                                              | ☐    |
| 5.9 | Open the **View** menu while on the Probe page.                                                                                                         | No entry for the extension page (not in this build); the built-in screens are listed.                                                                                                                                                                                                                                                                            | ☐    |

## 6. Widget canvas on Live Bench

| #    | Step                                                                                                                                                                                                                                                       | Expected                                                                                                                                                                                                                                                                      | Pass |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 6.1  | Rail → Live Bench (Project A, never touched before).                                                                                                                                                                                                       | Skeleton grid briefly, then ONE slot titled **Live Bench** with mono `wide`; header **Live Bench**, status line, `Saved`, and a **+ Add widget** button. `GET $A/projects/$PA/widget-layout` as ALICE → `layout: []` (the default is not written until you change something). | ☐    |
| 6.2  | Click **+ Add widget**.                                                                                                                                                                                                                                    | Modal "Add widget" with sections **Built-in** (Live Bench "Added", other built-ins with **Add**) and **Installed extensions**: **Hello Widget** **Add**; **Hello Probe** with ✓ and **Add**. No "Developer (this session)" section.                                           | ☐    |
| 6.3  | In Project A2 (no EDA), open the picker.                                                                                                                                                                                                                   | Hello Probe row shows mono `NEEDS EDA` and no Add. Disable Hello Widget in A2 (Store) → its row reads "disabled in this project" with no Add. Re-enable. Back to Project A.                                                                                                   | ☐    |
| 6.4  | Add **Hello Widget**.                                                                                                                                                                                                                                      | Modal closes; a new slot appended (scrolled into view) titled **Hello Widget**, size `compact`, showing "Hello from widget · 0.1.0". `Saving…` then `Saved` beside the header button.                                                                                         | ☐    |
| 6.5  | Add **Hello Probe**.                                                                                                                                                                                                                                       | Slot with the probe icon + **Hello Probe**, size `standard` (its preferred).                                                                                                                                                                                                  | ☐    |
| 6.6  | Open Hello Probe's `▾` menu.                                                                                                                                                                                                                               | Items **Compact** (disabled, tooltip "Too small for this widget" — minimum is standard), **Standard** ✓, **Wide**, **Full**, separator, **Move left**, **Move right** (disabled on the last slot). Pick **Wide** → the slot spans 3 of 4 columns; `Saving…` → `Saved`.        | ☐    |
| 6.7  | **Move left** on Hello Probe.                                                                                                                                                                                                                              | It swaps with Hello Widget. Escape / click outside closes the menu.                                                                                                                                                                                                           | ☐    |
| 6.8  | Click ✕ on the **Live Bench** slot.                                                                                                                                                                                                                        | Removed immediately, no confirm. Remove the other two → empty state "Nothing on your bench." / "Add the Live Bench widget, or any installed extension's widget." with **+ Add widget** and **Restore default**. **Restore default** → the single Live Bench slot returns.     | ☐    |
| 6.9  | Re-add both extension widgets, then `curl -s $A/projects/$PA/widget-layout -H "Authorization: Bearer $ALICE"`.                                                                                                                                             | `layout` lists `builtin:livebench`, `ext:hello-widget`, `ext:hello-probe` with their sizes.                                                                                                                                                                                   | ☐    |
| 6.10 | Quit and relaunch Solus, open Project A → Live Bench.                                                                                                                                                                                                      | Skeleton, then the saved arrangement — never a flash of the default first.                                                                                                                                                                                                    | ☐    |
| 6.11 | Per user: `curl -s $A/projects/$PA/widget-layout -H "Authorization: Bearer $VIEWER"`.                                                                                                                                                                      | `200` with `layout: []` — the viewer's own (empty) layout, not ALICE's.                                                                                                                                                                                                       | ☐    |
| 6.12 | Unknown ref: `curl -s -X PUT $A/projects/$PA/widget-layout -H "Authorization: Bearer $ALICE" -H 'Content-Type: application/json' -d '{"layout":[{"ref":"builtin:livebench","size":"wide"},{"ref":"ext:ghost","size":"compact"}]}'` then reopen Live Bench. | PUT `200`. Canvas renders the Live Bench slot only, with the note "1 widget from your saved layout isn't available and was removed." The next change (resize) saves a layout without `ext:ghost`.                                                                             | ☐    |
| 6.13 | Invalid layouts via curl: 25 slots; `{"ref":"ext:Bad Slug"}`; duplicate refs; `size:"huge"`.                                                                                                                                                               | Each `422 validation_error`.                                                                                                                                                                                                                                                  | ☐    |
| 6.14 | Stop the API. Resize a slot.                                                                                                                                                                                                                               | The grid keeps the change; beside the header: "Offline — layout kept on this machine until reconnected · Retry". Start the API, click **Retry** → `Saved`.                                                                                                                    | ☐    |
| 6.15 | Uninstall Hello Widget (Store) and return to Live Bench.                                                                                                                                                                                                   | Its slot body shows `ERROR` "hello-widget isn't installed in this project." with **Retry**; the slot's ✕ removes it. Reinstall Hello Widget → the slot is gone (removed) or renders again (if left in place).                                                                 | ☐    |
| 6.16 | Focus: in Context Model focus an entity, return to Live Bench.                                                                                                                                                                                             | The Hello Probe widget log shows `event focus.changed …` (it holds `graph.read`); Hello Widget shows nothing (no scope).                                                                                                                                                      | ☐    |

## 7. Settings tab and Permissions tab

| #    | Step                                                                                                                                                      | Expected                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Pass |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 7.1  | Store → Hello Probe → **Settings** tab.                                                                                                                   | Rows: "Enable in this project" (switch ON, sub "Turn this extension's widgets and checks on or off here."); "Verbose logging / verbose" (switch, off); "Run frequency / refresh" (select `every_sync`); "Row limit / limit" (number input 10, min 1 max 50); "Panel label / label" (text "Probe"). Footnote "Settings apply to this project only. Team defaults are set by an owner."                                                                                                       | ☐    |
| 7.2  | Turn **Verbose logging** on, pick `daily`, type 25, change the label to "Bench". Wait 1 s.                                                                | Each edit is saved ~400 ms after typing pauses. `GET $A/projects/$PA/extensions` → `settings {verbose:true, refresh:"daily", limit:25, label:"Bench"}`. The open Hello Probe widget logs `event settings.changed …`.                                                                                                                                                                                                                                                                        | ☐    |
| 7.3  | Type `999` into Row limit.                                                                                                                                | Red line under the fields: "Solus rejected that request. Check the values and try again." (server `422`). Server value stays 25. Type 40 → line clears.                                                                                                                                                                                                                                                                                                                                     | ☐    |
| 7.4  | Server-side shape checks via curl: PATCH `{"settings":{"nope":1}}`; `{"settings":{"refresh":"weekly"}}`; `{}`; `{"enabled":true,"extra":1}`.              | `422 validation_error` for each.                                                                                                                                                                                                                                                                                                                                                                                                                                                            | ☐    |
| 7.5  | Hello Widget → **Settings**.                                                                                                                              | Only the enable switch and "This extension has no settings of its own."                                                                                                                                                                                                                                                                                                                                                                                                                     | ☐    |
| 7.6  | Uninstall Hello Widget, open its Settings tab.                                                                                                            | Switch disabled; footnote "Install this extension to change its settings." Reinstall.                                                                                                                                                                                                                                                                                                                                                                                                       | ☐    |
| 7.7  | Hello Probe → **Permissions** tab.                                                                                                                        | Rows "Read the context model", "Keep its own data", "Ask SOL" each `GRANTED` (green); heading `MAY CONNECT TO` with `https://example.com` / "Requests go through Solus' proxy, never from your machine directly." `GRANTED`. Footnote "Grants are per project. Solus enforces these scopes at every call; revoke by uninstalling." Amber note "Extensions never write to hardware directly — anything that would move a motor goes through the approval queue, per your team instructions." | ☐    |
| 7.8  | Partial grant via curl: `PUT $A/projects/$PA/extensions/hello-probe` body `{"version":"1.0.0","grants":{"scopes":["graph.read"],"network":[]}}` as ALICE. | `200`. Permissions tab now shows "Keep its own data" and "Ask SOL" and the origin as `NOT GRANTED` (amber). The widget's `storage-set` button now returns `{error:{code:"scope_denied",message:"Scope not granted"}}`. Restore the full grant with the same PUT and all four values.                                                                                                                                                                                                        | ☐    |
| 7.9  | Undeclared grant: same PUT with `"scopes":["findings.write"]`.                                                                                            | `422 validation_error`, `details` lists `findings.write`.                                                                                                                                                                                                                                                                                                                                                                                                                                   | ☐    |
| 7.10 | Hello Widget → Permissions.                                                                                                                               | "This extension asks for no permissions." plus the footnote and amber note.                                                                                                                                                                                                                                                                                                                                                                                                                 | ☐    |
| 7.11 | Hello Probe → **Overview**.                                                                                                                               | WHAT IT ADDS: "Widget", "Page: Probe", "Window: Probe window", "Permissions / 3 scopes · 1 network origin". LINKS: **Documentation ↗**, **Report an issue ↗** (open in the OS browser); no Terms.                                                                                                                                                                                                                                                                                         | ☐    |

## 8. Update flow

| #   | Step                                                                                                                     | Expected                                                                                                                                                                                                                                                                                                                 | Pass |
| --- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---- |
| 8.1 | `pub hello-probe-1.1.0.zip "$PUB" key-hp-110`; wait for `approved`.                                                      | `202` then approved. `GET $A/projects/$PA/extensions` → hello-probe `update_available {version:"1.1.0", widens_permissions:false}`; `version.version` still `1.0.0`.                                                                                                                                                     | ☐    |
| 8.2 | Desktop Store (within 10 s).                                                                                             | Muted line "1 update available" under the header; the Hello Probe card shows `● INSTALLED ↑` (tooltip "Update available: 1.1.0"). Detail meta `QA Lab · v1.0.0 → 1.1.0 available · …`; primary **Update to 1.1.0** beside **Disable** / **Uninstall**. Frames still run 1.0.0.                                           | ☐    |
| 8.3 | Click **Update to 1.1.0**.                                                                                               | Button "Updating…"; no permissions step. Meta becomes `v1.1.0`; **Update** button gone. Cache: `hello-probe/1.1.0/` present and `1.0.0/` removed; index entry `version:"1.1.0"`. Widgets/page show `1.1.0` after remount. Settings values from §7 survived.                                                              | ☐    |
| 8.4 | `pub hello-probe-1.2.0.zip "$PUB" key-hp-120`; wait for `approved`.                                                      | Install row `update_available {version:"1.2.0", widens_permissions:true}`.                                                                                                                                                                                                                                               | ☐    |
| 8.5 | **Update to 1.2.0**.                                                                                                     | Modal `UPDATE HELLO PROBE` `v1.2.0`; body "1.2.0 additionally asks for" with ONE row "Read telemetry streams / telemetry.read / Live and recorded signal values of this project."; buttons **Cancel** / **Grant and update**.                                                                                            | ☐    |
| 8.6 | **Cancel**.                                                                                                              | Modal closes; meta still `v1.1.0 → 1.2.0 available`; frames keep running 1.1.0; Permissions tab unchanged.                                                                                                                                                                                                               | ☐    |
| 8.7 | **Update to 1.2.0** → **Grant and update**.                                                                              | Pinned `1.2.0`; Permissions tab gains "Read telemetry streams" `GRANTED`; server `granted_scopes` includes `telemetry.read`; cache dir `1.2.0/`.                                                                                                                                                                         | ☐    |
| 8.8 | Raw semantics via curl: re-pin to 1.1.0 with the current grants (`{"version":"1.1.0","grants":{…4 scopes…}}`).           | `200` (narrowing is applied silently; grants intersected). Then `{"version":"1.2.0","grants":{"scopes":["graph.read","storage.own","sol.ask"],"network":["https://example.com"]}}` → `409 grants_required` with `details[0].scopes == ["telemetry.read"]`.                                                               | ☐    |
| 8.9 | Unpublish the top version: `curl -s -X DELETE $A/extensions/hello-probe/versions/1.2.0 -H "Authorization: Bearer $PUB"`. | `204`. Catalog `latest_version` is `1.1.0`; an install pinned to 1.2.0 keeps running from its cache and its detail meta shows `v1.2.0` with no Update; `pub hello-probe-1.2.0.zip … key-hp-120-b` → `409 version_exists` (a version string is never reused). Republish as `1.2.1` if you need the widened version again. | ☐    |

## 9. Team policy via curl

`P=$A/teams/$TA/extensions/policies`. Hello Widget installed in Project A AND Project A2 first.

| #   | Step                                                                                                                                           | Expected                                                                                                                                                                                                                                                         | Pass |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 9.1 | `curl -s -w '%{http_code}' -X PUT $P/hello-widget -H "Authorization: Bearer $ALICE" -H 'Content-Type: application/json' -d '{"blocked":true}'` | `201`; body `{extension:{slug:"hello-widget",…}, blocked:true, default_installed:false, …}`.                                                                                                                                                                     | ☐    |
| 9.2 | `GET $A/projects/$PA/extensions` and `…/$PA2/extensions` as ALICE.                                                                             | In BOTH projects the hello-widget row has `enabled:false` and `policy.blocked:true`.                                                                                                                                                                             | ☐    |
| 9.3 | Desktop: Project A → Live Bench; Store → Hello Widget.                                                                                         | Its canvas slot shows `BLOCKED` "Blocked by your team."; Store card still `● INSTALLED`; Overview `BLOCKED BY TEAM` "An owner blocked this extension for your team."; clicking **Enable** → red status "Blocked by your team." (server `403 extension_blocked`). | ☐    |
| 9.4 | Same PUT as `$CAROL` (admin) and as `$VIEWER`.                                                                                                 | `403 forbidden` for both. As `$BOB` → `404 not_found` (not a member of team A).                                                                                                                                                                                  | ☐    |
| 9.5 | `PUT $P/hello-widget` with `{"blocked":true,"default_installed":true}`; with `{}`; with `{"default_settings":{"x":1}}` for `hello-probe`.      | `422 validation_error` each (contradictory; empty; undeclared key).                                                                                                                                                                                              | ☐    |
| 9.6 | `curl -s -X DELETE $P/hello-widget -H "Authorization: Bearer $ALICE"` then re-read installs.                                                   | `204`. Rows still `enabled:false` — unblocking does NOT re-enable. Store → Hello Widget → **Enable** now succeeds (`enabled:true`). Repeat in A2. A second DELETE → `404`.                                                                                       | ☐    |
| 9.7 | `GET $P` as ALICE.                                                                                                                             | `200`, `data: []` after the reset (cursor-paginated envelope).                                                                                                                                                                                                   | ☐    |

## 10. Bridge behaviour, observed from the test extension

Use the Hello Probe widget on Live Bench (Project A, fully granted) unless stated. Every result
is printed in the widget's log; the host never shows bridge refusals in Solus chrome.

| #     | Step                                                                                                                                                                                              | Expected                                                                                                                                                                                                                                             | Pass |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 10.1  | Log at load.                                                                                                                                                                                      | `event init {extensionId:"hello-probe", version:"1.x.x", projectId, settings:{…the four fields…}, theme:{…css vars…}, focus:null or the current focus, mode:"widget"}` then `ui.ready → "ok"`. No token, URL or header appears anywhere in `init`.   | ☐    |
| 10.2  | **focus** with nothing focused; then focus an entity in Context Model and press again.                                                                                                            | `null`; then the entity object (scoped to Project A).                                                                                                                                                                                                | ☐    |
| 10.3  | **storage-set** then **storage-get**.                                                                                                                                                             | `{}` then `{value:"hi <timestamp>"}`. Server: `curl -s $A/projects/$PA/extensions/hello-probe/storage/greeting -H "Authorization: Bearer $ALICE"` → `200 {data:{key:"greeting", value:"hi …", size_bytes, updated_at}}`.                             | ☐    |
| 10.4  | Same storage GET as `$VIEWER`; as `$BOB`; and `…/extensions/hello-widget/storage/greeting` as ALICE.                                                                                              | `200` (reads have no role floor); `404`; `403 scope_denied` (hello-widget holds no `storage.own`).                                                                                                                                                   | ☐    |
| 10.5  | **fetch-ok**.                                                                                                                                                                                     | `{status:200, headers:{…}, body:"<!doctype html>…", encoding:"text"}` — fetched by Solus' proxy.                                                                                                                                                     | ☐    |
| 10.6  | **fetch-denied** (`https://example.org`, undeclared).                                                                                                                                             | `{error:{code:"network_denied", message:"Network target not allowed"}}`.                                                                                                                                                                             | ☐    |
| 10.7  | **unknown**.                                                                                                                                                                                      | `{error:{code:"unknown_method", message:"Unknown method"}}`.                                                                                                                                                                                         | ☐    |
| 10.8  | **bad-params** (`projectId` in params).                                                                                                                                                           | `{error:{code:"invalid_params", message:"Invalid params"}}` — a frame can never name a project.                                                                                                                                                      | ☐    |
| 10.9  | **burst** (70 concurrent `settings.get`).                                                                                                                                                         | `{total:70, rate_limited:N}` with `N > 0` (limits: 60 per rolling 10 s and 8 in flight, per extension across its frames). Wait 10 s; a single **focus** works again.                                                                                 | ☐    |
| 10.10 | **sol** (requires SOL configured with a model key and ALICE having credits).                                                                                                                      | `{answer:"…"}` after a few seconds; the conversation "Extension: hello-probe" appears in the SOL sidebar; Billing/usage shows the debit against ALICE. Without SOL configured: `{error:{code:"unavailable", …}}` — not a fabricated answer.          | ☐    |
| 10.11 | Hello Widget's widget (no scopes): press **focus**, **storage-set**, **fetch-ok**, **sol**.                                                                                                       | Each `{error:{code:"scope_denied", message:"Scope not granted"}}`.                                                                                                                                                                                   | ☐    |
| 10.12 | Dev mode: Settings → Developer → load `hello-probe/` (the extension is installed). Return to Live Bench and the Probe page.                                                                       | Hello Probe's slot chrome and the page header show a `DEV` badge and version `dev`; the frame reports `mode:"dev"`; `init.version` is `"dev"`. Edit `index.html` (change the `<h1>`), **Reload** in Settings → the frames remount with the new text. | ☐    |
| 10.13 | In the dev copy press **sol**, **storage-set**, **fetch-ok**, **focus**.                                                                                                                          | `sol` and `storage-set` → `{error:{code:"blocked", message:"Extension is not available in this project"}}` (server-attributed methods are refused in dev mode); `fetch-ok` and `focus` still work (declared origin / scope, session-local grants).   | ☐    |
| 10.14 | **Remove** the dev registration.                                                                                                                                                                  | Frames remount on the installed version; badges gone.                                                                                                                                                                                                | ☐    |
| 10.15 | Attribution header forgery via curl: `POST $A/projects/$PA/sol/conversations/{id}/messages` with `X-Solus-Extension: hello-widget` (no `sol.ask` grant) and with `X-Solus-Extension: not a slug`. | `403 scope_denied` for both — never silently downgraded to an unattributed turn.                                                                                                                                                                     | ☐    |

## 11. Isolation and honesty

| #    | Step                                                                                                                                                                                                                                                  | Expected                                                                                                                                                                                                                 | Pass |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---- |
| 11.1 | `GET $A/projects/$PA/extensions` as `$BOB`; `PUT …/extensions/hello-widget` as BOB; `GET …/widget-layout` as BOB.                                                                                                                                     | `404 not_found` for all three (a foreign project does not exist for BOB).                                                                                                                                                | ☐    |
| 11.2 | `GET $A/projects/$PA/extensions` as `$VIEWER`.                                                                                                                                                                                                        | `200` — the viewer sees the install rows (needed to render views).                                                                                                                                                       | ☐    |
| 11.3 | As VIEWER: `PUT …/extensions/hello-widget {"grants":{"scopes":[],"network":[]}}`; `PATCH … {"enabled":false}`; `DELETE …`; `PUT …/widget-layout`.                                                                                                     | `403 forbidden` for every write.                                                                                                                                                                                         | ☐    |
| 11.4 | (Optional) Sign the desktop in as VIEWER, open Project A → Store → Hello Probe → Install → Grant and install.                                                                                                                                         | Inline error in the modal "Only project members can change extensions here."                                                                                                                                             | ☐    |
| 11.5 | BOB in Project B: `GET $A/extensions` and install `hello-widget` in `$PB` (`PUT $A/projects/$PB/extensions/hello-widget {"grants":{"scopes":[],"network":[]}}`).                                                                                      | Catalog `200` (tenant-free); install `201`. Nothing in any catalog response names team A or B; `install_count` is an aggregate only. ALICE's `GET …/$PA/extensions` is unaffected.                                       | ☐    |
| 11.6 | Same storage key in two projects: PUT `…/$PB/extensions/hello-widget/storage/greeting` as BOB (needs `storage.own` — hello-widget has none → expect `403 scope_denied`). Use hello-probe in a KiCad-equipped Project B if you want the positive case. | Values never cross projects or extensions; `403 scope_denied` where the grant is missing.                                                                                                                                | ☐    |
| 11.7 | Honest numbers.                                                                                                                                                                                                                                       | CREDITS card always `This cycle —`. A withdrawn extension (§8.9, unpublish ALL versions of a throwaway extension you installed) shows `— installs` and "no longer in the catalog" in its meta. No run timeline anywhere. | ☐    |
| 11.8 | Unauthenticated: any extensions route without a token.                                                                                                                                                                                                | `401 unauthorized`.                                                                                                                                                                                                      | ☐    |

## 12. Cross-feature

| #    | Step                                                                                                                          | Expected                                                                                                                                                                                                                                                                                         | Pass |
| ---- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---- |
| 12.1 | With the Probe window open and Hello Probe's detail page open, **Sign out** (menu row), then sign back in and open the Store. | Catalog shows (no stale detail page). Installs, grants, settings and the canvas layout are all still there (server-side; sign-out clears nothing on the server). The Probe window is NOT closed automatically — close it with `Cmd/Ctrl+W`; it cannot be reopened until a project is open again. | ☐    |
| 12.2 | Settings → Appearance: switch theme and accent, return to Live Bench and the Probe page.                                      | Slot chrome, page header, DEV badges, cards and menus re-skin. Each frame's log shows `event theme.changed {…}`; the extension itself decides what to do with it.                                                                                                                                | ☐    |
| 12.3 | Rail → SOL, chat normally.                                                                                                    | SOL page unaffected by installed extensions; the "Extension: hello-probe" conversation from §10.10 is a normal conversation in the sidebar.                                                                                                                                                      | ☐    |
| 12.4 | Close the main window (macOS: keep the app running) with the Probe window open.                                               | The extension window closes with the main window or shows "Open a project in the main Solus window to use hello-probe here." on reopen — it never runs headless with a project of its own.                                                                                                       | ☐    |
| 12.5 | Store → `+ Create extension`.                                                                                                 | Dialog "Create an extension" explaining the manifest model, "The in-app authoring flow is not available in this build yet.", link **Read the manifest documentation ↗**, **Close**.                                                                                                             | ☐    |
| 12.6 | Sources: disconnect the KiCad source from Project A, open the Store and the picker.                                           | Hello Probe (installed) stays installed and its frames keep running; in the picker it shows `NEEDS EDA` only for a NEW add; the detail's REQUIRES dot turns amber. Reconnect.                                                                                                                    | ☐    |

## Known limitations (not defects)

- Developer registrations have no rail entry, picker row or "Open" button of their own; they
  render only by overriding an installed extension with the same id. The "Developer (this
  session)" picker section, the per-dev-extension permissions step, and the DEV-badge tooltip
  counters (dropped/refused messages) did not ship.
- Dev registrations persist across restarts (in `index.json`), contrary to the wireflow's
  session-only wording.
- `NOT GRANTED` on the Permissions tab is reachable only through a partial grant made via the
  API (§7.8); the desktop always grants the whole declared set.
- Install counts come straight from the catalog aggregate and read `N installs` even for 1;
  `— installs` appears only for an install whose version left the catalog.
- The Overview "IN THIS PROJECT" card never shows `DOWNLOADING`; it is `IDLE` as soon as the
  server row exists. Download progress is visible only in the slot/page skeleton.
- Review `rejected` cannot be produced through the public publish path (the same checks run at
  upload and return `422 bundle_invalid`).
- Extension windows are not closed on sign-out; the main window's project switch leaves an
  extension page for Overview rather than remounting it.
- The rail caps extension entries at 8 with no overflow menu; the View menu lists no extension
  pages.
- SOL grounding, a per-extension credit meter, and the in-app authoring/publish flow are not in
  this build.
- Rate limits and the publish idempotency store are per API process; restarting the API resets
  them.
