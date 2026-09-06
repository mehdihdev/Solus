# `extension.toml` reference

The manifest is the whole declaration of an extension: one TOML file at the bundle root, decoded
and validated by the same contract on the server (publish), the desktop (developer mode, install)
and the Store. It is treated as untrusted developer input: unknown fields reject at every level,
every free-text field is capped, file references are relative and traversal-free, and nothing in it
can name a command.

Source of truth: `docs/contracts/extension-manifest.md`;
`packages/shared-types/src/extension-manifest.ts` (`MANIFEST_LIMITS`);
`packages/contracts/python/solus_contracts/extension_manifest.py` (`LIMITS`). Companion pages:
[getting started](getting-started.md), [bridge API](bridge-api.md), [publishing](publishing.md).

## Top level

| Key              | Type    | Required | Rule                                                                                                |
| ---------------- | ------- | -------- | --------------------------------------------------------------------------------------------------- |
| `schema_version` | integer | yes      | `1` or `2`. A higher number is "newer than this Solus" (listed, not loaded) and rejected at publish |
| `[extension]`    | table   | yes      | Identity — see below                                                                                |
| `[views]`        | table   | yes      | At least one of `widget`, `page`, `window`                                                          |
| `[permissions]`  | table   | no       | Defaults to no scopes, no network                                                                   |
| `[settings]`     | table   | no       | Defaults to no fields                                                                               |
| `[store]`        | table   | yes      | `overview` is required                                                                              |
| `[backend]`      | table   | no       | **schema_version 2, first-party only** — see below                                                  |
| `[graph]`        | table   | no       | **schema_version 2, first-party only** — see below                                                  |
| `[tools]`        | table   | no       | **schema_version 2, first-party only** — see below                                                  |

The manifest text itself must be valid UTF-8 and ≤ 64 KiB.

## `[extension]`

| Field       | Type            | Required | Rule                                                                                                                                                                                                     |
| ----------- | --------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`        | string          | yes      | `^[a-z][a-z0-9-]{1,63}$` (2–64 chars). Unique case-insensitively across the registry; doubles as the cache folder name. `__proto__`, `constructor`, `prototype` are reserved                             |
| `name`      | string          | yes      | 1–60 chars, display only                                                                                                                                                                                 |
| `version`   | string          | yes      | Semver `MAJOR.MINOR.PATCH` with optional `-prerelease`; **no** `+build` metadata. Never reusable once published                                                                                          |
| `publisher` | string          | yes      | 1–60 chars, display only. Your registry identity is your account; the first publish seeds your publisher display name from this field                                                                    |
| `summary`   | string          | yes      | 1–160 chars; shown on the Store card                                                                                                                                                                     |
| `requires`  | array of arrays | no       | AND of ORs over source kinds `code \| eda \| cad \| canbus \| runtime`; ≤ 4 groups, each non-empty and distinct. The Store uses it to suggest the extension for projects with matching connected sources |
| `min_solus` | string          | no       | Semver floor for the host                                                                                                                                                                                |

```toml
requires = [["eda"], ["code", "runtime"]]   # needs an EDA source AND (a code source OR a runtime source)
```

## `[views]`

Declare one, two or all three. Every `entry` is a bundle-relative `.html` path.

### `views.widget`

| Field       | Type   | Required | Rule                                                                                          |
| ----------- | ------ | -------- | --------------------------------------------------------------------------------------------- |
| `entry`     | path   | yes      | `.html`                                                                                       |
| `preferred` | string | yes      | Slot size hint: `compact \| standard \| wide \| full` (a coarse hint the canvas may override) |
| `minimum`   | string | no       | Same set; below this the canvas may hide the widget                                           |

### `views.page`

| Field   | Type   | Required | Rule                                                                                                 |
| ------- | ------ | -------- | ---------------------------------------------------------------------------------------------------- |
| `entry` | path   | yes      | `.html`                                                                                              |
| `icon`  | path   | yes      | `.svg`, ≤ 16 KiB, reduced to the monochrome subset — see [icon rules](getting-started.md#icon-rules) |
| `label` | string | yes      | 1–24 chars, the rail label                                                                           |

### `views.window`

| Field    | Type    | Required | Rule                                                 |
| -------- | ------- | -------- | ---------------------------------------------------- |
| `entry`  | path    | yes      | `.html`                                              |
| `title`  | string  | yes      | 1–60 chars; the OS window title (sanitized by Solus) |
| `width`  | integer | no       | 320–4096 px; default 960                             |
| `height` | integer | no       | 320–4096 px; default 640                             |

```toml
[views]
widget = { entry = "widget.html", preferred = "wide", minimum = "standard" }
page   = { entry = "page.html", icon = "icon.svg", label = "BOM" }
window = { entry = "window.html", title = "BOM — full table", width = 960, height = 640 }
```

## `[permissions]`

| Field     | Type            | Required | Rule                                                                                                                                                                          |
| --------- | --------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scopes`  | array of string | no       | From the closed set below; ≤ 8; distinct                                                                                                                                      |
| `network` | array of string | no       | https **origins** — `https://host[:port]`, lowercase, no path, no query, no trailing slash, at least one dot in the host (`https://localhost` is not accepted); ≤ 8; distinct |

Declaring anything here — one scope or one origin — makes `store.privacy_policy` required.

### Scopes (closed set, v1)

| Scope            | Unlocks (bridge methods / events)                                                                           |
| ---------------- | ----------------------------------------------------------------------------------------------------------- |
| `graph.read`     | `graph.getFocus`, `graph.getEntity`, `graph.getNeighborhood`, `graph.search`; also receives `focus.changed` |
| `telemetry.read` | `telemetry.subscribe`, `telemetry.unsubscribe`; receives `telemetry.sample`                                 |
| `sources.read`   | `sources.list` — connected sources and their sync status (never credentials or URLs)                        |
| `findings.write` | `findings.create` — raise a cross-domain finding in the open project                                        |
| `sol.ask`        | `sol.ask` — one SOL turn, metered to the invoking user, attributed to your extension                        |
| `storage.own`    | `storage.get/set/delete` — your own per-project key-value store, ≤ 256 KiB total                            |
| `focus.read`     | `focus.get`; receives `focus.changed`                                                                       |
| `focus.write`    | `focus.propose` — propose a focus change; the host arbitrates                                               |

Users may grant fewer scopes than you declare; the bridge answers `scope_denied` for the rest.
Adding a scope to Solus is a contract change; there is no way to request one from a manifest.

### Network

`permissions.network` is not a scope. It is the exact-origin allowlist `net.fetch` may reach:
https only, origin compared as a whole string, resolved addresses must be public (no private,
loopback, link-local or cloud-metadata ranges), redirects only within the same origin. Users grant
origins individually at install.

```toml
[permissions]
scopes  = ["graph.read", "sources.read"]
network = ["https://api.octopart.com"]
```

## `[settings]`

Typed fields that Solus renders in the extension's Settings tab and stores per project on the
server. Values reach the frame in `init.settings`, via `settings.get`, and as `settings.changed`
events. Settings are for non-secret preferences — never put credentials here.

`settings.fields` is an array of tables, ≤ 16 fields, keys unique.

| Field     | Type            | Required    | Rule                                                      |
| --------- | --------------- | ----------- | --------------------------------------------------------- |
| `key`     | string          | yes         | `^[a-z][a-z0-9_]{0,31}$`                                  |
| `type`    | string          | yes         | `boolean \| number \| string \| select`                   |
| `label`   | string          | yes         | 1–40 chars                                                |
| `options` | array of string | select only | 1–12 options, each 1–40 chars; not allowed on other types |
| `default` | matches `type`  | no          | Must be the declared type; for `select`, one of `options` |
| `min`     | number          | number only | Lower bound applied to user input                         |
| `max`     | number          | number only | Upper bound applied to user input                         |

How Solus renders them: `boolean` → toggle; `number` → numeric input clamped to `min`/`max`;
`string` → text input; `select` → dropdown of `options`. On save the server validates the whole
object against the **pinned** version's manifest (unknown key, wrong type, value outside options
or range, encoded object > 16 KiB → `422`). Missing keys fall back to `default`; a key with neither
a value nor a default is absent from `settings`.

```toml
[settings]
[[settings.fields]]
key = "refresh"
type = "select"
label = "Run frequency"
options = ["every_sync", "hourly", "daily", "manual"]
default = "every_sync"

[[settings.fields]]
key = "flag_eol"
type = "boolean"
label = "Flag end-of-life parts"
default = true

[[settings.fields]]
key = "max_rows"
type = "number"
label = "Rows per page"
min = 10
max = 500
default = 100

[[settings.fields]]
key = "vendor"
type = "string"
label = "Preferred vendor"
```

## `[store]`

What the Store shows. Every value here is a bundle-relative file reference or an https URL — never
inline markup.

| Field            | Type            | Required                        | Rule                                                                           |
| ---------------- | --------------- | ------------------------------- | ------------------------------------------------------------------------------ |
| `overview`       | path            | yes                             | `.md`, ≤ 32 KiB; the Overview tab                                              |
| `privacy_policy` | path            | when any permission is declared | `.md`, ≤ 32 KiB; linked from the permissions step and the detail page          |
| `links`          | table           | no                              | Keys `documentation`, `issues`, `terms`; each an https URL ≤ 2048 chars        |
| `screenshots`    | array of path   | no                              | `.png` or `.webp`, ≤ 6, ≤ 1 MiB each; the file signature must match the suffix |
| `sections`       | array of tables | no                              | ≤ 4 of `{ title, body }`: `title` 1–40 chars, `body` a `.md` path ≤ 16 KiB     |

```toml
[store]
overview = "OVERVIEW.md"
privacy_policy = "PRIVACY.md"
links = { documentation = "https://example.com/docs", issues = "https://example.com/issues" }
screenshots = ["shots/table.png", "shots/finding.webp"]

[[store.sections]]
title = "How it works"
body = "docs/HOW.md"
```

Markdown files are rendered as text-safe Markdown. They may not contain `<script`, `<iframe`,
`javascript:` links or `on*=` attributes (rejected at publish). Links in Markdown may be https.

### Privacy policy

Required as soon as you declare a scope or a network origin, because that is the moment the
extension can read project data or send bytes off the machine. It is shown to every user before
they grant. State what you read, what you store (`storage.own`), what you send and to which origins,
and whether you call SOL (`sol.ask` is metered to the user's own credits).

## `[backend]`, `[graph]`, `[tools]` — first-party only (schema_version 2)

These three tables exist so a bundle Solus ships can add server-side capability: routes, SOL
tools and a graph node type. They are a **declaration, not code** — the zip never carries Python.
Publishing a manifest that uses any of them requires a Solus staff account and an in-repo
capability package with the same id; anyone else gets `422 bundle_invalid` with
`backend: first-party only (publisher is not Solus staff)`. At `schema_version = 1` they are
unknown fields. Community bundles do not need them: the bridge is the whole API.

| Table / field        | Type            | Rule                                                                                                                                                                         |
| -------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend.capability` | string          | Must equal `extension.id`                                                                                                                                                    |
| `backend.routes`     | boolean         | Default `false`. `true` mounts the package's router at `/api/v1/projects/{project_id}/widgets/<id>/`                                                                         |
| `graph.kinds`        | array of tables | ≤ 8 of `{ name, domain }`; `name` `^[a-z][a-z0-9_]{0,31}$` and distinct; `domain` ∈ `code \| electrical \| mechanical \| simulation \| runtime`. Stored as `ext:<id>:<name>` |
| `tools.names`        | array of string | ≤ 16, distinct, same name rule. Registered with SOL as `<id>.<name>`                                                                                                         |

```toml
schema_version = 2

[backend]
capability = "fixture-bundle"
routes = true

[graph]
kinds = [{ name = "note", domain = "code" }]

[tools]
names = ["add_note", "clear_notes"]
```

Uninstalling a first-party bundle soft-deletes the graph entities of its declared kinds in that
project, removes its settings, storage and canvas slots — nothing of it remains.

## File references

Every path in the manifest (`entry`, `icon`, `overview`, `privacy_policy`, `screenshots[]`,
`sections[].body`):

- relative to the bundle root, no leading `/`, no backslashes;
- segments match `[A-Za-z0-9_.-]+`, none is `.` or `..`, whole path ≤ 200 chars;
- the suffix must be the one the field allows (`.html`, `.svg`, `.md`, `.png`/`.webp`), compared
  case-insensitively;
- the file must exist in the bundle and be within its byte cap (checked at publish).

## Byte caps (`MANIFEST_LIMITS` / `LIMITS`)

| Cap                             | Value  |
| ------------------------------- | ------ |
| Page icon                       | 16 KiB |
| Overview / privacy              | 32 KiB |
| Section body                    | 16 KiB |
| Screenshot                      | 1 MiB  |
| Bundle (uncompressed)           | 25 MiB |
| Manifest text                   | 64 KiB |
| Settings object (stored values) | 16 KiB |

## What fails validation

Problems are reported as `"<dotted.path>: <message>"`, one per problem, and the list is identical in
developer mode (`Settings → Developer`) and on the publish route (`422 bundle_invalid`,
`details[]`). The messages below are the TypeScript contract's wording; the Python side produces the
same paths with pydantic's phrasing for type errors (for example `extension.name: String should
have at most 60 characters`). Find them in `packages/shared-types/src/extension-manifest.ts` and
`packages/contracts/python/solus_contracts/extension_manifest.py`.

| Path                                                              | Message                                                                                                                                                                             |
| ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `manifest`                                                        | `must be a table` (the file did not decode to a table)                                                                                                                              |
| `schema_version`                                                  | `must be an integer` · `must be one of 1, 2` · `3 is newer than 2`                                                                                                                  |
| `manifest.backend` / `.graph` / `.tools` (at schema_version 1)    | `unknown field`                                                                                                                                                                     |
| `backend.capability`                                              | `must be a lowercase slug (2–64 chars)` · `must equal extension.id`                                                                                                                 |
| `backend.routes`                                                  | `must be a boolean`                                                                                                                                                                 |
| `graph.kinds`                                                     | `must be a list of at most 8 kinds` · `entries must be distinct` · `.N.name: must be a lowercase snake_case name (≤32 chars)` · `.N.domain: must be one of code, …`                 |
| `tools.names`                                                     | `must be a list of at most 16 names` · `entries must be distinct` · `.N: must be a lowercase snake_case name (≤32 chars)`                                                           |
| `manifest.<key>` / `<table>.<key>`                                | `unknown field` — at every level, including inside `[store]`                                                                                                                        |
| `extension.id`                                                    | `must be a lowercase slug (2–64 chars)` · `reserved id`                                                                                                                             |
| `extension.name` etc.                                             | `must be a string` · `length must be 1–60`                                                                                                                                          |
| `extension.version`, `extension.min_solus`                        | `must be semver`                                                                                                                                                                    |
| `extension.requires`                                              | `must be a list of at most 4 groups` · `.N: each group must be a non-empty list of kinds` · `.N.M: must be one of code, eda, cad, canbus, runtime` · `.N: entries must be distinct` |
| `views`                                                           | `must be a table` · `must declare at least one of widget, page, window`                                                                                                             |
| `views.<kind>.entry`, `views.page.icon`                           | `must be a relative path inside the bundle ending in .html` (or `.svg`)                                                                                                             |
| `views.widget.preferred` / `.minimum`                             | `must be one of compact, standard, wide, full`                                                                                                                                      |
| `views.page.label`                                                | `length must be 1–24`                                                                                                                                                               |
| `views.window.width` / `.height`                                  | `must be an integer 320–4096`                                                                                                                                                       |
| `permissions.scopes`                                              | `must be a list of at most 8 scopes` · `.N: must be one of graph.read, …` · `entries must be distinct`                                                                              |
| `permissions.network`                                             | `must be a list of at most 8 https origins` · `.N: must be an https origin (no path)` · `entries must be distinct`                                                                  |
| `settings.fields`                                                 | `must be a list of at most 16 fields` · `entries must be distinct` (duplicate keys)                                                                                                 |
| `settings.fields.N.key`                                           | `must be a lowercase snake_case key (≤32 chars)`                                                                                                                                    |
| `settings.fields.N.type`                                          | `must be one of boolean, number, string, select`                                                                                                                                    |
| `settings.fields.N.options`                                       | `must list 1–12 options` · `select fields must list options` · `only select fields take options`                                                                                    |
| `settings.fields.N.default`                                       | `must be one of options` · `must be a <type>`                                                                                                                                       |
| `settings.fields.N.min`                                           | `only number fields take min/max` · `must be a number`                                                                                                                              |
| `store.overview`, `store.privacy_policy`, `store.sections.N.body` | `must be a relative path inside the bundle ending in .md`                                                                                                                           |
| `store.privacy_policy`                                            | `required when permissions.scopes or permissions.network is non-empty`                                                                                                              |
| `store.links.<key>`                                               | `must be an https URL`                                                                                                                                                              |
| `store.screenshots`                                               | `must be a list of at most 6 images` · `.N: must be a relative path inside the bundle ending in .png/.webp`                                                                         |
| `store.sections`                                                  | `must be a list of at most 4 sections` · `.N.title: length must be 1–40`                                                                                                            |

Bundle-level problems (missing referenced files, over-cap files, disallowed file types, the static
content checks) are reported by the publish validator only — see
[publishing → what review checks](publishing.md#what-the-review-checks).

## Full example

Every block populated (the contract's `manifest-full` fixture, as TOML):

```toml
schema_version = 1

[extension]
id = "bom"
name = "BOM"
version = "1.2.0"
publisher = "Solus"
summary = "Bill of materials from your EDA project — sourcing status, findings flag affected lines."
requires = [["eda"]]
min_solus = "1.0.0"

[views]
widget = { entry = "widget.html", preferred = "wide", minimum = "standard" }
page = { entry = "page.html", icon = "icon.svg", label = "BOM" }
window = { entry = "window.html", title = "BOM — full table", width = 960, height = 640 }

[permissions]
scopes = ["graph.read", "sources.read"]
network = ["https://api.octopart.com"]

[settings]
[[settings.fields]]
key = "refresh"
type = "select"
label = "Run frequency"
options = ["every_sync", "hourly", "daily", "manual"]
default = "every_sync"

[[settings.fields]]
key = "flag_eol"
type = "boolean"
label = "Flag end-of-life parts"
default = true

[[settings.fields]]
key = "max_rows"
type = "number"
label = "Rows per page"
min = 10
max = 500
default = 100

[[settings.fields]]
key = "vendor"
type = "string"
label = "Preferred vendor"

[store]
overview = "OVERVIEW.md"
privacy_policy = "PRIVACY.md"
links = { documentation = "https://docs.solusforge.com/extensions/bom", issues = "https://gitlab.com/solusforge/solus/-/issues", terms = "https://solusforge.com/terms" }
screenshots = ["shots/table.png", "shots/finding.webp"]

[[store.sections]]
title = "How it works"
body = "docs/HOW.md"
```

Minimal valid manifest (one view, no permissions, no settings):

```toml
schema_version = 1

[extension]
id = "hello-widget"
name = "Hello"
version = "0.1.0"
publisher = "Your name"
summary = "Greets whatever is focused."

[views]
widget = { entry = "widget.html", preferred = "compact" }

[store]
overview = "OVERVIEW.md"
```
