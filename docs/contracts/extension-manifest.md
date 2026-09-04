# Extension Manifest Contract — `extension.toml`

**Ticket:** SOLUSDEV-235 · **ADR:** ADR-035 (with the ADR-034 amendment) · **Ratified:** in-session
2026-09-03 (Mehdi), second-founder check at the MR (ADR-032 tier-2).
**Shapes:** `packages/shared-types/src/extension-manifest.ts` (TypeScript) ·
`packages/contracts/python/solus_contracts/extension_manifest.py` (Python).
**Fixtures:** `packages/shared-types/fixtures/extension-manifest/` — validated by BOTH suites; the
`_fields.json` manifest is regenerated from the pydantic field names
(`packages/api/tests/contracts/test_extension_manifest_contract.py`) and checked by the TS field
lists.

## What this contract covers

The ONE file every extension bundle carries at its root, `extension.toml`, decoded to an object.
Three consumers read it and must agree: the API's publish validator (Python), the desktop's
developer mode and installer (TypeScript, main process), and the Store UI (TypeScript, renderer).
Both parsers take the decoded TOML object, never TOML text, so the JSON fixtures and API bodies
validate through the same code.

A manifest is **untrusted developer input** (CLAUDE.md §7). Unknown fields reject everywhere; every
free-text field is capped; file references are relative, traversal-free, and suffix-checked;
nothing in the manifest can name a command or trigger execution.

## The file

```toml
schema_version = 1

[extension]
id = "bom"                      # ^[a-z][a-z0-9-]{1,63}$ — also the folder name; unique case-insensitively
name = "BOM"                    # ≤ 60
version = "1.2.0"               # semver
publisher = "Solus"             # ≤ 60 (display; identity is the registry account)
summary = "Bill of materials from your EDA project."   # ≤ 160
requires = [["eda"]]            # AND of ORs over code | eda | cad | canbus | runtime; ≤ 4 groups
min_solus = "1.0.0"             # optional semver floor for the host

[views]                         # at least one of the three
widget = { entry = "widget.html", preferred = "wide", minimum = "standard" }   # CTR-01 slot sizes
page   = { entry = "page.html", icon = "icon.svg", label = "BOM" }            # label ≤ 24
window = { entry = "window.html", title = "BOM", width = 960, height = 640 }   # px 320–4096

[permissions]                   # optional; empty when absent
scopes  = ["graph.read", "sources.read"]      # closed set below, ≤ 8, distinct
network = ["https://api.octopart.com"]        # https ORIGINS only (no path), ≤ 8, distinct

[settings]                      # optional; rendered by Solus, values stored per project server-side
[[settings.fields]]             # ≤ 16 fields, unique keys ^[a-z][a-z0-9_]{0,31}$
key = "refresh"
type = "select"                 # boolean | number | string | select
label = "Run frequency"         # ≤ 40
options = ["every_sync", "hourly", "daily", "manual"]   # select only; 1–12 options, each ≤ 40
default = "every_sync"          # must match the type (and be one of options for select)
# number fields may carry min / max

[store]
overview = "OVERVIEW.md"        # required
privacy_policy = "PRIVACY.md"   # REQUIRED when permissions.scopes or permissions.network is non-empty
links = { documentation = "https://…", issues = "https://…", terms = "https://…" }   # https only
screenshots = ["shots/table.png"]                     # ≤ 6, .png/.webp
[[store.sections]]                                    # ≤ 4 custom sections
title = "How it works"                                # ≤ 40
body = "docs/HOW.md"
```

## Closed permission scopes (v1)

| scope            | what the host bridge lets the extension do                                    |
| ---------------- | ----------------------------------------------------------------------------- |
| `graph.read`     | read entities, relations and neighbourhoods of the open project               |
| `telemetry.read` | subscribe to live / recorded signals of the open project                      |
| `sources.read`   | list connected sources and their sync status                                  |
| `findings.write` | raise cross-domain findings in the open project                               |
| `sol.ask`        | ask SOL — metered to the invoking user, attributed to the extension (ADR-035) |
| `storage.own`    | read / write the extension's own per-project key-value store (≤ 256 KiB)      |
| `focus.read`     | read the shared focus                                                         |
| `focus.write`    | propose a focus change (the host arbitrates)                                  |

Adding a scope is a contract change (tier-2). Network egress is separate: `permissions.network`
lists the https origins the bridge's fetch proxy may reach; anything else is refused at call time.

## Validation rules (identical on both sides; the fixtures prove it)

- `schema_version` must be `1`. A newer version is reported as `newer` by the TS parser (the
  desktop treats such a bundle as read-only) and rejected by the Python validator (the server
  never partially accepts a manifest it does not understand).
- Unknown fields reject at every level, including inside `[store]`; custom content goes in
  `[[store.sections]]` bodies, which are file references, never inline markup.
- File references: relative, no leading `/`, no backslash, no `.`/`..` segments, segment chars
  `[A-Za-z0-9_.-]`, ≤ 200 chars, suffix in the allowed set for that field (`.html`, `.svg`,
  `.md`, `.png`/`.webp`).
- `id` also rejects `__proto__`, `constructor`, `prototype` (object-internal names).
- Byte caps for referenced files are exported for the bundle validator and the desktop installer
  (`MANIFEST_LIMITS` / `LIMITS`): icon 16 KiB, overview 32 KiB, section 16 KiB, screenshot 1 MiB,
  bundle 25 MiB.

## Parsed shape

```ts
interface ExtensionManifest {
  readonly schema_version: 1;
  readonly extension: ExtensionMeta; // id, name, version, publisher, summary, requires, min_solus?
  readonly views: Views; // widget? | page? | window?
  readonly permissions: Permissions; // scopes: PermissionScope[], network: string[]  (defaults [])
  readonly settings: Settings; // fields: SettingField[]                       (default [])
  readonly store: Store; // overview, privacy_policy?, links, screenshots, sections
}
```

`parseExtensionManifest(decoded)` (TS) returns `{ ok, manifest }` or
`{ ok: false, reason: "invalid" | "newer", problems: string[] }`; `parse_extension_manifest` (Python)
raises `ValidationError`, and `manifest_problems(decoded)` returns the same dotted-path problem
strings (`"views.page.entry: must be a relative path …"`) so the developer mode and the publish
validator show identical messages.

## Fixtures

| file                           | expectation                                                |
| ------------------------------ | ---------------------------------------------------------- |
| `manifest-full.json`           | valid; every block populated                               |
| `manifest-minimal.json`        | valid; optional blocks absent → defaulted                  |
| `bad-id.invalid.json`          | id with a space and a capital → `extension.id`             |
| `missing-privacy.invalid.json` | scope declared, no privacy policy → `store.privacy_policy` |
| `unknown-field.invalid.json`   | `postinstall` command field → `extension.postinstall`      |
| `traversal.invalid.json`       | `../../index.html` entry → `views.page.entry`              |
| `newer-schema.json`            | `schema_version: 2` → TS `newer`, Python reject            |
