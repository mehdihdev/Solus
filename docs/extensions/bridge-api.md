# Bridge API

The runtime API as seen from inside an extension frame. Everything here is `postMessage` JSON: the
frame sends requests to `window.parent`, the host answers exactly once per request and pushes
unsolicited events. There is no SDK to install; the [`bridge.js` in getting started](getting-started.md#bridgejs)
is a complete client.

Ground truth: `apps/desktop/src/renderer/src/features/extensions/host/bridgeProtocol.ts`
(`METHOD_SCOPES`, `BRIDGE_LIMITS`, error codes), `host/paramsSchema.ts` (params), `host/handlers/*`
(results), `docs/architecture/extensions-runtime.md` §5–§8. Companion pages:
[manifest](manifest.md), [publishing](publishing.md).

## Message shapes

```ts
// frame → host
{ v: 1, id: string, method: string, params: object }

// host → frame — exactly one per request id
{ v: 1, id: string, ok: true,  result: unknown }
{ v: 1, id: string, ok: false, error: { code: ErrorCode, message: string } }

// host → frame — unsolicited
{ v: 1, event: string, data: unknown }
```

- `v` is always `1`.
- `id` is yours: 1–64 chars of `[A-Za-z0-9_-]`, unique among your in-flight requests, echoed
  verbatim. Reusing an in-flight id is refused with `invalid_params`.
- `method` ≤ 64 chars; `params` must be a plain object (send `{}` when a method takes none).
- The serialized request must be ≤ **64 KiB**.
- Anything that is not exactly this shape is **dropped without a response** — no error comes back
  (an error would be an oracle). Dropped counts are visible in the `DEV` badge tooltip.
- Post to `window.parent` with target origin `'*'`; accept inbound messages only when
  `event.source === window.parent`.

## Handshake

1. The frame's document loads. The host posts the `init` event.
2. Your code sends `ui.ready` (`{}`). The host answers `{}` and the frame fades in. If `ui.ready`
   arrives before `init` was posted, the host posts `init` first, then the reply.
3. If `ui.ready` has not arrived within **10 s** of load, the frame is shown as "didn't start"
   with a Reload action (the frame stays mounted but hidden).

Until `ui.ready` completes, the only event delivered is `init`. Requests are answered regardless.

### The `init` payload

```ts
{
  v: 1, event: 'init',
  data: {
    extensionId: string,                                  // your manifest id
    version: string,                                      // your semver, or 'dev'
    projectHandle: string,                                // per-mount random opaque handle — never accepted back as scope
    settings: Record<string, boolean | number | string>,  // your declared fields, defaults applied
    theme: Record<string, string>,                        // CSS variables, see Theme below
    focus: Focus | null,                                  // the shared focus (no scope needed for this snapshot)
    mode: 'widget' | 'page' | 'window' | 'dev'            // 'dev' for any developer registration, whatever the view
  }
}
```

`Focus` (from `docs/contracts/focus.md`):

```ts
interface Focus {
  entity: { projectId: string; entityId: string };
  domain: "code" | "electrical" | "mechanical" | "simulation" | "runtime";
  label?: string; // display name cached from the graph
  path: FocusStep[]; // ancestry excluding the current entity, oldest first
}
interface FocusStep {
  entity: { projectId; entityId };
  domain;
  label?;
  relation: string;
}
```

### Theme

`init.theme` and `theme.changed` carry the host's CSS variables as `{ '--bg': '#…', … }`:
`--bg --sur --sur2 --bd --tx --mut --ok --warn --err --sw --ee --me --rt --acc --acc-ink`
(background, surfaces, border, text, muted text, status colours, per-domain colours, accent and
accent ink). Set them on `document.documentElement` and reference them from your CSS.

## Scope model

Each method requires at most one scope from the manifest's closed set. A call is authorized in this
order, and the first failure is the answer:

1. Install snapshot: not installed / disabled / team-blocked → `blocked`.
2. Method not in the table → `unknown_method`.
3. Developer registration calling a server-attributed method (`sol.ask`, `findings.create`,
   `storage.*`) → `blocked`.
4. Required scope not **granted** by the user for this project → `scope_denied` (declaring a
   scope is not the same as being granted it).
5. Duplicate in-flight id, then the rate limiter (`rate_limited`), then params validation
   (`invalid_params`), then the handler.

Scope always comes from the host. `params` may never carry `projectId`, `project_id`, `teamId` or
`team_id` — their presence alone is `invalid_params`. Unknown param keys are `invalid_params` too;
every validator returns a fresh object containing only the declared keys.

## Methods

Caps below are on the string's length in characters unless marked "bytes" (UTF-8). Optional params
marked `?`; defaults in parentheses.

### Unscoped

| Method            | Params                       | Result                                 | Notes                                                                                                                                                                                                                  |
| ----------------- | ---------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ui.ready`        | `{}`                         | `{}`                                   | Completes the handshake                                                                                                                                                                                                |
| `settings.get`    | `{}`                         | `Record<key, boolean\|number\|string>` | Your own declared fields (a fresh copy)                                                                                                                                                                                |
| `ui.openExternal` | `{ url }` — https URL ≤ 2048 | `{}`                                   | Opens the OS browser — only for an origin in your granted `permissions.network` or an exact URL from your `[store].links`; anything else → `network_denied`. 3 per 60 s → `rate_limited`. Non-https → `invalid_params` |

### `graph.read`

| Method                  | Params                                                         | Result                                          |
| ----------------------- | -------------------------------------------------------------- | ----------------------------------------------- |
| `graph.getFocus`        | `{}`                                                           | `Entity \| null` — the focused entity           |
| `graph.getEntity`       | `{ entityId ≤ 128 }`                                           | the API's entity object (see below)             |
| `graph.getNeighborhood` | `{ entityId, depth? (1) 0–2, limit? (200) 1–200 }`             | `{ entities: Entity[], relations: Relation[] }` |
| `graph.search`          | `{ q 1–200, types? ([]) ≤ 16 strings ≤ 64, limit? (50) 1–50 }` | `Entity[]`                                      |

Entity shape (public keys of the API's `serialize_entity`; `graph.getFocus` returns the host's
compact form with the first five):

```ts
{
  id,
    type,
    domain,
    name,
    source_key,
    project_id,
    source_id,
    origin,
    properties,
    version,
    created_at,
    updated_at;
}
```

Relation: `{ id, type, from_entity_id, to_entity_id }`. Every relation's endpoints are in
`entities`. `graph.search` narrows on one `type` server-side and filters the rest client-side.

### `telemetry.read`

| Method                  | Params                              | Result               | Notes                                                                                                                                                               |
| ----------------------- | ----------------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `telemetry.subscribe`   | `{ signalIds: 1–32 strings ≤ 128 }` | `{ subscriptionId }` | ≤ 8 live subscriptions per frame (more → `invalid_params` "Too many subscriptions"); samples arrive as `telemetry.sample` batched at ≤ 10 events/s per subscription |
| `telemetry.unsubscribe` | `{ subscriptionId ≤ 128 }`          | `{}`                 | Unknown id → `invalid_params`                                                                                                                                       |

**Current build:** the Live Bench stream fan-out is not yet wired to the bridge; `telemetry.subscribe`
answers `unavailable`. Declare the scope now and handle `unavailable` gracefully.

### `sources.read`

| Method         | Params | Result                                                                                                                                                                                    |
| -------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sources.list` | `{}`   | `[{ id, kind, name, status, lastSyncAt }]` — `status` ∈ `pending \| connected \| syncing \| error \| disconnected`; `lastSyncAt` ISO string or `null`. No credentials, no config, no URLs |

### `findings.write`

| Method            | Params                                                                                                  | Result          |
| ----------------- | ------------------------------------------------------------------------------------------------------- | --------------- |
| `findings.create` | `{ title 1–120, body ≤ 4 KiB bytes, severity ∈ info\|warning\|critical, entityIds? ([]) ≤ 16 × ≤ 128 }` | `{ findingId }` |

Title and body are stored and rendered as text, never markup. **Current build:** no findings write
route exists yet; the method answers `unavailable`. Dev registrations answer `blocked`.

### `sol.ask`

| Method    | Params                                                  | Result               |
| --------- | ------------------------------------------------------- | -------------------- |
| `sol.ask` | `{ prompt 1 char – 8 KiB bytes, entityIds? ([]) ≤ 16 }` | `{ answer: string }` |

What happens: the host makes an ordinary SOL turn with the **user's** session, adding
`X-Solus-Extension: <id>` and `X-Solus-Extension-Version: <version>`. The server accepts the header
only when the project has an enabled, unblocked install of your extension that grants `sol.ask`;
otherwise the turn is refused (`403 scope_denied` → `blocked`), never downgraded to an unattributed
turn. On acceptance:

- the turn is **metered to the invoking user's credits** and their frequency caps — there is no
  extension budget and no pooling; out of credits → the frame sees `unavailable`;
- the debit is recorded with your extension id/slug/version as the attribution;
- one conversation per (project, extension), titled `Extension: <id>`, is created lazily and
  reused for the life of the frame's host; it is visible in the user's SOL chat sidebar;
- each ask is one guide-mode turn; your `prompt` is wrapped **as data** inside Solus's own
  instructions — you can ask a question, not issue instructions; `entityIds` are validated but not
  used to assemble context in this build;
- the `answer` is the assistant's text. Render it as text.

Dev registrations answer `blocked`.

### `storage.own`

| Method           | Params                                                 | Result                      | Notes                                                      |
| ---------------- | ------------------------------------------------------ | --------------------------- | ---------------------------------------------------------- |
| `storage.get`    | `{ key }`                                              | `{ value: string \| null }` | `null` on a miss                                           |
| `storage.set`    | `{ key, value: string ≤ 64 KiB bytes (may be empty) }` | `{}`                        | Total for (project, extension) ≤ 256 KiB → `storage_quota` |
| `storage.delete` | `{ key }`                                              | `{}`                        | Deleting a missing key succeeds                            |

`key` matches `^[A-Za-z0-9_.-]{1,64}$`. Values are opaque strings to the bridge (serialize JSON
yourself). Storage is per (project, extension): another project or another extension can never
read it, and it is deleted on uninstall. Server-side rate limit: 120 writes/min per install →
`rate_limited`. Dev registrations answer `blocked`.

### `focus.read` / `focus.write`

| Method          | Scope         | Params                                                                                                         | Result                  |
| --------------- | ------------- | -------------------------------------------------------------------------------------------------------------- | ----------------------- |
| `focus.get`     | `focus.read`  | `{}`                                                                                                           | `Focus \| null`         |
| `focus.propose` | `focus.write` | `{ entityId ≤ 128, domain ∈ code\|electrical\|mechanical\|simulation\|runtime, label? ≤ 256, relation? ≤ 64 }` | `{ accepted: boolean }` |

The host builds the target in **its** project and arbitrates. With `relation` the hop is appended
to the current trail via `descend()`; without it the focus "landed here directly" (empty path). A
current focus from another project, or a trail `descend()` refuses, is `invalid_params`.
`accepted: false` means the host declined (for example the project changed underneath).

### `net.fetch` (no scope — `permissions.network`)

| Params                                                                                                                     | Result                                                                                           |
| -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `{ url ≤ 2048, method? ('GET') ∈ GET\|POST\|PUT\|DELETE, headers? ({}) ≤ 32 entries, values ≤ 4096, body? ≤ 1 MiB bytes }` | `{ status: number, headers: Record<string,string>, body: string, encoding: 'text' \| 'base64' }` |

Rules, enforced by the host and again by the main process (which re-reads the allowlist from the
cached manifest, not from the message):

- `url` must be `https:` and its origin must be in the user's **granted** `permissions.network`
  (exact string match) → otherwise `network_denied`.
- Resolved addresses must be public: private, loopback, link-local (including cloud metadata),
  CGNAT, multicast and unspecified ranges are refused → `network_denied`.
- Redirects: up to 3, followed only while the origin is unchanged → otherwise `network_denied`.
- Timeout 15 s → `unavailable`. Response > 5 MiB → `network_denied` ("response too large").
- You may not set `cookie`, `host`, `origin`, `referer` or `authorization` (→ `invalid_params`);
  the proxy additionally strips `proxy-authorization`, `content-length`, `connection`,
  `transfer-encoding`. No Solus cookie or credential ever rides along — put your own API key in a
  header yourself if the target needs one (and say so in your privacy policy).
- Only `content-type`, `content-length`, `etag`, `last-modified` come back in `headers`.
- `body` is returned as text when the content-type is textual (`text/*`, JSON, XML, JavaScript,
  form-encoded, `+json`/`+xml`), else base64 with `encoding: 'base64'`.
- Outside Electron (there is no proxy) → `unavailable`.

## Events (host → frame)

| Event              | Data                                                    | When                                                                                 |
| ------------------ | ------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `init`             | see above                                               | After the frame's `load` (and before the `ui.ready` reply if that came first)        |
| `focus.changed`    | `Focus \| null`                                         | The shared focus moved — only to frames granted `focus.read` **or** `graph.read`     |
| `settings.changed` | `Record<key, value>`                                    | The user saved this extension's Settings tab (the full object, defaults applied)     |
| `theme.changed`    | `Record<cssVar, value>`                                 | Theme or accent changed                                                              |
| `project.changed`  | `{}`                                                    | The host's project changed; frames are remounted right after — treat as a full reset |
| `telemetry.sample` | `{ subscriptionId, samples: [{ signalId, t, value }] }` | While a subscription is live — only to frames granted `telemetry.read`               |

Events are not acknowledged. Nothing but `init` is delivered before `ui.ready`.

## Limits

| Limit        | Value                                                                                                | On breach                                           |
| ------------ | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| Message size | 64 KiB serialized                                                                                    | dropped                                             |
| Request rate | 60 requests per rolling 10 s, **per extension across all its frames** (a widget and a page share it) | `rate_limited`                                      |
| In flight    | 8 concurrent requests per extension                                                                  | `rate_limited` (does not consume the window)        |
| Handshake    | `ui.ready` within 10 s of load                                                                       | frame shown as failed                               |
| Telemetry    | 8 subscriptions per frame, 32 signals each, batches at ≤ 10/s                                        | `invalid_params`                                    |
| Storage      | key ≤ 64 chars, value ≤ 64 KiB, 256 KiB per (project, extension), 120 writes/min                     | `invalid_params` / `storage_quota` / `rate_limited` |
| `net.fetch`  | body ≤ 1 MiB, response ≤ 5 MiB, 15 s, 3 same-origin redirects, 32 headers                            | `invalid_params` / `network_denied` / `unavailable` |
| `sol.ask`    | prompt ≤ 8 KiB; the user's own credit and frequency limits                                           | `invalid_params` / `unavailable`                    |

## The CSP you run under

Every `.html` in your bundle is served with this header (from `solus-ext://<id>/<version>/…`,
where `'self'` is your bundle and nothing else):

```
default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' data:; font-src 'self'; connect-src 'none'; frame-src 'none';
object-src 'none'; base-uri 'none'; form-action 'none'
```

Consequences:

- **No network from the frame.** `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`,
  `sendBeacon` all fail — and their mere presence in your JS fails review. Use `net.fetch` with a
  declared origin.
- **No remote scripts, stylesheets, fonts or images** (`img-src` also allows `data:` URIs). Vendor
  everything into the bundle; only `.js .css .json .svg .png .webp .woff2 .md .html` are served.
- **No inline `<script>`** — `<script src="file.js">` only. Inline `style` attributes and `<style>`
  blocks work in the current build; a stylesheet file is the portable choice.
- No `<iframe>`, `<object>`, `<embed>`, `<base>`, `<form action="https://…">`, no navigation of the
  host. Workers and service workers are rejected at review.
- The frame's origin is opaque (`sandbox="allow-scripts"` without `allow-same-origin`):
  `localStorage`, cookies and `document.cookie` are unavailable — use `storage.own`.
- `window.open` / `<a target="_blank">` do nothing useful; use `ui.openExternal` (granted origins or your store links only, 3 per minute).

The page's `<title>` is ignored for window views (the manifest's `title` wins).

## Developer-mode differences

- `init.version === 'dev'`, `init.mode === 'dev'` for every view kind.
- Grants are session-local (never written to the server).
- `sol.ask`, `findings.create`, `storage.get/set/delete` → `blocked`.
- Files are served from your folder with no hash check; **Reload** remounts with a cache-busting
  nonce.
- Only the manifest is validated; the static content checks run at publish.

## Error codes

Every `{ ok: false }` carries one of these codes and a short, fixed message that never echoes a
server body, a stack, a URL or an id you did not already have.

| Code             | Meaning                                                                                                                                                                                                    |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `unknown_method` | Not in the method table                                                                                                                                                                                    |
| `scope_denied`   | The method's scope is not granted for this project                                                                                                                                                         |
| `invalid_params` | Schema validation failed: unknown key, scope key, over-cap value, bad enum, duplicate in-flight id, unknown subscription/storage key, cross-project focus, or a server `404`/`422`/`413 payload_too_large` |
| `rate_limited`   | Over 60 / 10 s or 8 in flight; or a server `429`                                                                                                                                                           |
| `network_denied` | `net.fetch` target not https, origin not granted, private address, cross-origin redirect, disallowed method, response too large                                                                            |
| `blocked`        | Not installed / disabled / team-blocked in this project; a dev registration calling a server-attributed method; a server `403`                                                                             |
| `storage_quota`  | `storage.set` would exceed 256 KiB for this (project, extension)                                                                                                                                           |
| `unavailable`    | The host is offline, the API call failed or timed out, the user is out of SOL credits, or the capability is not wired in this build                                                                        |
| `internal`       | Host-side fault (logged with context on the host)                                                                                                                                                          |

The first seven are refusals and are recorded as `extension.bridge_refused` data events; the last
two are faults.

## Troubleshooting

| Symptom / code                                             | Likely cause                                                                                                                                            | Fix                                                                                                                   |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Frame shows "didn't start" after 10 s                      | `ui.ready` never sent; script blocked by CSP (inline `<script>`, remote `src`); entry 404                                                               | Load scripts with `<script src>`; check the entry path in the manifest; in dev, the tooltip shows the path that 404'd |
| No reply at all to a request                               | Message dropped: bad shape, `v !== 1`, `id` not `[A-Za-z0-9_-]{1,64}`, `params` not an object, > 64 KiB                                                 | Fix the envelope; check the dropped counter in the `DEV` badge tooltip                                                |
| `unknown_method`                                           | Typo, or a method that does not exist                                                                                                                   | Compare with the tables above                                                                                         |
| `scope_denied`                                             | Scope not declared, or declared but not granted by the user                                                                                             | Add it to `permissions.scopes` (plus a privacy policy); ask the user to re-grant in the Store                         |
| `invalid_params` on a call that "looks right"              | A `projectId`/`teamId` key, an extra key, an over-cap string, a non-integer `depth`/`limit`, a non-https `ui.openExternal` URL, a reused in-flight `id` | Send only the declared keys with values in range                                                                      |
| `invalid_params` "Not found"                               | The entity/key does not exist in this project                                                                                                           | Handle as a miss                                                                                                      |
| `blocked` on `storage.*` / `sol.ask` in dev                | Dev registrations have no install row                                                                                                                   | Test these against a published (even unlisted) version installed in a test project                                    |
| `blocked` everywhere                                       | Extension disabled or team-blocked in this project                                                                                                      | Nothing to fix in code; the user or a team owner decides                                                              |
| `network_denied`                                           | Origin missing from `permissions.network` or not granted; http; IP in a private range; cross-origin redirect                                            | Declare the exact `https://host` origin; avoid redirects to CDNs on other origins                                     |
| `network_denied` "response too large"                      | Response body > 5 MiB                                                                                                                                   | Page or filter server-side                                                                                            |
| `rate_limited`                                             | > 60 requests / 10 s or > 8 in flight, summed across your widget + page frames                                                                          | Debounce, batch (`graph.getNeighborhood` instead of many `getEntity`), keep ≤ 8 in flight                             |
| `storage_quota`                                            | 256 KiB per project exhausted                                                                                                                           | Delete stale keys; store less                                                                                         |
| `unavailable` on `telemetry.subscribe` / `findings.create` | Not wired in this build                                                                                                                                 | Degrade gracefully; keep the scope declared                                                                           |
| `unavailable` on `sol.ask`                                 | Offline, SOL error, or the user has no credits                                                                                                          | Tell the user in your UI; retry later                                                                                 |
| `unavailable` on `net.fetch`                               | Timeout (15 s), DNS failure, network error, or running outside Electron                                                                                 | Retry with backoff                                                                                                    |
| Styles ignored / wrong colours                             | Theme variables never applied                                                                                                                           | Copy `init.theme` onto `document.documentElement` and listen to `theme.changed`                                       |
| `focus.changed` never arrives                              | Neither `focus.read` nor `graph.read` granted, or `ui.ready` not sent                                                                                   | Declare/grant the scope; complete the handshake                                                                       |
