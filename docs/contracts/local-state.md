# Local State — machine-local files under `~/.solus`

**Ratified:** in-session at the SOLUSDEV-166 MR (ADR-034). Design: `docs/architecture/solus-folder.md`.
**Shapes:** `packages/shared-types/src/local-state.ts` (TypeScript) ·
`packages/contracts/python/solus_contracts/local_state.py` (Python).
**Fixtures:** `packages/shared-types/fixtures/local-state/` — validated by BOTH suites; the
`_fields.json` manifest is regenerated from the pydantic serialization aliases
(`packages/companion/tests/test_local_state_contract.py`) and checked by the TS field lists.

## What this contract covers

The machine-local, private, never-synced layer of ADR-034: files under `~/.solus/` on the user's
computer. The team-shared repo `.solus/` layer (TOML) is a separate, later contract. The
**project-level `.solus`** (SOLUSDEV-240) is server-stored — see `docs/api/solus.md`; it never
touches this directory.

| Path                                  | Contents                                                                                                                                                                                                                                                                                                                                                                            | Writer               | Readers                               |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------------------------------------- |
| `~/.solus/companion_id`               | 32-hex machine identity (pre-dates this)                                                                                                                                                                                                                                                                                                                                            | companion            | companion                             |
| `~/.solus/projects.json`              | `ProjectRegistry` — project→working-copy                                                                                                                                                                                                                                                                                                                                            | desktop MAIN process | desktop main, companion               |
| `~/.solus/config.json`                | machine prefs — **reserved**, schema TBD                                                                                                                                                                                                                                                                                                                                            | —                    | —                                     |
| `~/.solus/projects/<id>/`             | `sol/<conversationId>.json` — SOL chat cache (`{schema_version: 1, items: [{role, content}]}`, 0600, atomic writes, 2 MB byte cap; ADR-034 amendment 2026-09-01). Other content **reserved**                                                                                                                                                                                        | desktop MAIN process | desktop main/renderer                 |
| `~/.solus/logs/`                      | log files — **reserved** (Ticket E)                                                                                                                                                                                                                                                                                                                                                 | —                    | —                                     |
| `~/.solus/extensions/<id>/<version>/` | extracted extension bundle — `extension.toml`, assets, entry HTML/JS (a machine-local CACHE of an installed version; the registry is the source of truth). 0600 files under 0700 dirs; content-hash verified before first use; **never executed by main** — served read-only to sandboxed frames via `solus-ext://`; deletable at any time (ADR-034 amendment 2026-09-03 / ADR-035) | desktop MAIN process | desktop main (`solus-ext://` handler) |
| `~/.solus/extensions/index.json`      | `ExtensionIndex` — installed extension id → `{ version, contentHash, installedAt, source, devPath? }` (`schema_version` 1, 1 MiB cap, atomic writes)                                                                                                                                                                                                                                | desktop MAIN process | desktop main                          |

Reserved entries are named by ADR-034 but carry no schema yet; a schema lands here (and in both
packages) before the first byte is written to them.

## `projects.json` — the project registry

```json
{
  "schema_version": 1,
  "projects": {
    "<projectId>": {
      "path": "/absolute/working/copy",
      "repoUrl": "https://gitlab.com/team/rover.git",
      "lastOpenedAt": "2026-08-30T17:05:00Z"
    }
  }
}
```

- `schema_version` (required, integer ≥ 1). Currently `1`.
- `projects` (required): map of project id → link. Keys must match `^[A-Za-z0-9_-]+$` — a project
  id becomes a **path segment** (`~/.solus/projects/<id>/`), so separators, dot-segments and
  escapes are rejected at the contract boundary.
- `path` (required, non-empty): absolute path of the working copy on THIS machine.
- `repoUrl`, `lastOpenedAt` (optional, informational).
- Unknown fields reject on both sides (`extra="forbid"` / strict TS parse).
- Naming: entry fields are camelCase and `schema_version` is snake_case — exactly the shape
  ratified in ADR-034. Python bridges via aliases; dump with `by_alias=True`.

## `extensions/index.json` — the installed-extension index

```json
{
  "schema_version": 1,
  "installed": {
    "bom": {
      "version": "1.2.0",
      "contentHash": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
      "installedAt": "2026-09-03T10:00:00Z",
      "source": "registry"
    },
    "my-widget": {
      "version": "0.0.0-dev",
      "contentHash": "0000000000000000000000000000000000000000000000000000000000000000",
      "installedAt": "2026-09-03T10:05:00Z",
      "source": "dev",
      "devPath": "/Users/ada/src/my-widget"
    }
  }
}
```

- `schema_version` (required, integer ≥ 1). Currently `1`.
- `installed` (required): map of extension id → entry. Keys must satisfy `EXTENSION_ID_RE`
  (`^[a-z][a-z0-9-]{1,63}$`, `packages/shared-types/src/extension-manifest.ts`) AND not be an
  object-internal name (`__proto__`/`constructor`/`prototype`) — the id becomes a **path
  segment** (`~/.solus/extensions/<id>/<version>/`), so anything else is rejected at the contract
  boundary. `version` is likewise a path segment and must be strict semver.
- `version` (required): the installed semver; names the bundle directory.
- `contentHash` (required): lower-case sha256 hex (64 chars) of the bundle bytes as recorded by
  the registry (`extension_versions.content_hash`, `docs/schemas/extensions.md` §4.3). The main
  process re-hashes the cached bundle and refuses to serve it when the two differ. For `dev`
  entries it is informational (the unpacked folder is re-read each launch).
- `installedAt` (required, RFC 3339 UTC).
- `source` (required): `"registry"` — installed from the Store, bundle under
  `~/.solus/extensions/<id>/<version>/` — or `"dev"` — developer mode pointing at an unpacked
  folder; never published (ADR-035 §4).
- `devPath` (optional; **required when `source` is `"dev"`, forbidden otherwise**): absolute path
  of the unpacked folder. Validated like a workspace path (canonicalized; rejected under `~/.solus`,
  the filesystem root or the user's home itself).
- Unknown fields reject on both sides (`extra="forbid"` / strict TS parse).
- Byte cap **1 MiB** (`EXTENSION_INDEX_MAX_BYTES`); a larger file is treated as corrupt.
- Naming follows `projects.json`: entry fields camelCase, `schema_version` snake_case. Python
  bridges via aliases; dump with `by_alias=True`.
- **Corrupt → empty index** (`{ schema_version: 1, installed: {} }`) — the cached bundle
  directories are then unreferenced and the installer re-derives the index from the registry's
  install list on next sync. **Newer `schema_version` → read-only** (ground rule 6): the desktop
  neither installs nor removes bundles until it is upgraded.
- The registry server remains the source of truth for what a project has installed
  (`extension_installs`); this file only says which bundles THIS machine holds. Nothing here is a
  secret, and no token or API base URL is ever written into a bundle directory (Layer-1 rules).

**Contract twins.** The TypeScript shape (`ExtensionIndex`, `parseExtensionIndex`) lands in
`packages/shared-types/src/local-state.ts` with the desktop installer task; the Python twin
(`solus_contracts.local_state.ExtensionIndex`) and the shared fixtures under
`packages/shared-types/fixtures/local-state/` land with task **EXT-05**. Until EXT-05 lands, this
section is the contract; the ADR-034 amendment of 2026-09-03 governs the file's existence and
rules, and any format change amends ADR-034 and ADR-035 together.

## Ground rules (all `~/.solus` files)

1. **JSON only** for machine-written files (the companion's zero-YAML posture stands).
2. **Every file carries `schema_version`.**
3. **Atomic writes**: write a temp file in the same directory, then rename.
4. **`~/.solus` is 0700** (`SOLUS_HOME_MODE`); creation and takeover both enforce it.
5. **Never secrets.** `HOME` survives the companion's `env -i` scrub, so MCP fork processes can
   read this directory. Tokens, credentials, and BYO-license material are banned; so are
   server-owned settings (`sol_mode`, consent, onboarding step), which must stay cross-machine.
6. **Newer `schema_version` ⇒ read-only.** A reader that finds a version above what it knows
   (TS: `{ ok: false, reason: "newer" }`; Python: `ValidationError`) must leave the file
   untouched — rewriting it would turn a downgrade into data loss.
7. **Corrupt files never crash a reader**; parse failures degrade to the empty registry (and the
   corrupt file may then be overwritten — only _newer_ files are protected).

## The registry file is untrusted input

Because forks run as the user and can write `~/.solus`, and the file can be hand-edited or predate
the current build, every value is validated at **both** the write and the read boundary — the read
side is the real trust boundary for the companion sink:

- **Project ids** must satisfy `isSafeProjectId` (the id shape AND not an object-internal name —
  `__proto__`/`constructor`/`prototype`), enforced by both the TS and Python parsers.
- **Workspace paths** handed to a fork (`SOLUS_COMPANION_WORKSPACE`) are canonicalized (symlinks
  and `.`/`..` resolved) and rejected if they carry control characters, resolve to the filesystem
  root / the user's home / `~/.solus` or its subtree, or — on Windows only — contain the cmd.exe
  metacharacter class (`" & ^ | < > % ! * ?`) that the `launch.cmd` fork twin would interpret. The
  canonical value is what gets stored. On POSIX those metacharacters are legal directory-name
  characters and are allowed (`bin/launch` quotes the value under `env -i`).
- **`repoUrl`** is stripped of embedded credentials before being persisted or returned to the
  renderer: http(s) userinfo (including a bare `token@host`) is removed, an ssh `git@` username is
  kept (it is required to clone), and a credential-bearing opaque value is dropped entirely. Legacy
  files are cleaned on read.

## Consumers

- **Desktop main** (`apps/desktop/src/main/`): owns registry writes; derives
  `SOLUS_COMPANION_WORKSPACE` from the active project's entry at companion spawn. The renderer's
  `projectFolderStore` (localStorage) is a display cache, never the source of truth.
- **Desktop main — extension installer / `solus-ext://` protocol**: owns `extensions/index.json`
  and the bundle directories; verifies `contentHash` before serving a bundle; the renderer never
  touches these paths directly (ADR-035 §1, §4).
- **Companion**: today only `companion_id`; later tickets may read `projects.json` via
  `solus_contracts.local_state`.
