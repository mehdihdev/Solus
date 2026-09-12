# Local State — machine-local files under `~/.solus`

**Last updated:** 2026-09-07. Hardware source/hint extension approved in-session for SOLUSDEV-251 (ADR-034).

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

| Path                                  | Contents                                                                                                                                                                                                                                                                                                                                                                                                          | Writer               | Readers                               |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------------------------------------- |
| `~/.solus/companion_id`               | 32-hex machine identity (pre-dates this)                                                                                                                                                                                                                                                                                                                                                                          | companion            | companion                             |
| `~/.solus/projects.json`              | `ProjectRegistry` — project→working-copy                                                                                                                                                                                                                                                                                                                                                                          | desktop MAIN process | desktop main, companion               |
| `~/.solus/config.json`                | machine prefs — **reserved**, schema TBD                                                                                                                                                                                                                                                                                                                                                                          | —                    | —                                     |
| `~/.solus/projects/<id>/`             | `sol/<conversationId>.json` — SOL chat cache (`{schema_version: 1, items: [{role, content}]}`, 0600, atomic writes, 2 MB byte cap; ADR-034 amendment 2026-09-01). `hardware.json` is specified below; other content **reserved**                                                                                                                                                                                  | desktop MAIN process | desktop main/renderer                 |
| `~/.solus/preferences.json`           | `EngineeringPreferences` — the user's engineering conventions (`schema_version` 1; `freeText` ≤ 2,400 chars, `codeStyle`/`mechanical`/`electrical`/`documentation`/`unitsStandards` ≤ 800 chars each, `updatedAt`); the one Layer-1 file the USER authors. 0600, atomic writes, 64 KiB byte cap; attached to each SOL turn by the desktop, never stored server-side (ADR-034 amendment 2026-09-06 / SOLUSDEV-244) | desktop MAIN process | desktop main/renderer                 |
| `~/.solus/logs/`                      | log files — **reserved** (Ticket E)                                                                                                                                                                                                                                                                                                                                                                               | —                    | —                                     |
| `~/.solus/extensions/<id>/<version>/` | extracted extension bundle — `extension.toml`, assets, entry HTML/JS (a machine-local CACHE of an installed version; the registry is the source of truth). 0600 files under 0700 dirs; content-hash verified before first use; **never executed by main** — served read-only to sandboxed frames via `solus-ext://`; deletable at any time (ADR-034 amendment 2026-09-03 / ADR-035)                               | desktop MAIN process | desktop main (`solus-ext://` handler) |
| `~/.solus/extensions/index.json`      | `ExtensionIndex` — installed extension id → `{ version, contentHash, installedAt, source, devPath? }` (`schema_version` 1, 1 MiB cap, atomic writes)                                                                                                                                                                                                                                                              | desktop MAIN process | desktop main                          |

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

## `preferences.json` — the user's engineering preferences (HOME H3)

```json
{
  "schema_version": 1,
  "updatedAt": "2026-09-06T12:00:00Z",
  "freeText": "Prefer 0.1 mm clearance minimum on all boards.",
  "codeStyle": "C++17, no dynamic allocation in ISRs.",
  "mechanical": "Metric fasteners only; 6061-T6 unless stated.",
  "electrical": "JST-GH for signal, XT30 for power.",
  "documentation": "Every board ships with a one-page bring-up note.",
  "unitsStandards": "SI units; ISO 2768-m general tolerances."
}
```

- `schema_version` (required, integer ≥ 1). Currently `1`.
- `freeText` (required, string, ≤ `PREFERENCES_FREE_TEXT_CAP` = 2,400 chars) and the five structured
  fields `codeStyle`, `mechanical`, `electrical`, `documentation`, `unitsStandards` (required,
  strings, ≤ `PREFERENCES_FIELD_CAP` = 800 chars each). Empty strings are the empty document.
- `updatedAt` (optional, RFC 3339 UTC, informational).
- Unknown fields reject (strict TS parse). Byte cap **64 KiB** (`PREFERENCES_MAX_BYTES`); a larger
  file is treated as corrupt. **Corrupt → empty document**; **newer `schema_version` → read-only**
  (ground rule 6). Over-cap strings are truncated on read, never rejected — the user's text is
  theirs; the cap bounds what reaches a prompt.
- This is a **document the user writes**, not settings — no toggles, no server-owned values, no
  secrets. It is the Solus equivalent of a `claude.md`: how this person engineers.
- **Transport.** The server never reads `~/.solus`. The desktop renderer loads the document through
  a sender-gated IPC and attaches it to each SOL turn as `MessageCreate.preferences`; the API
  validates it against a strict schema with the same caps and hands it to the prompt only as a
  nonce-fenced `engineering_preferences` data block (`agent/prompt.py`). Nothing is stored
  server-side; the transcript keeps the message, not the preferences.
- **Contract twin.** TypeScript only (`EngineeringPreferences`, `parseEngineeringPreferences`,
  `emptyEngineeringPreferences` in `packages/shared-types/src/engineering-preferences.ts`). No Python twin: no
  Python process reads this file — the companion never consumes it and the API validates the
  request body with its own Pydantic schema (ADR-034 amendment 2026-09-06).
- One file per machine. Two accounts on one machine share it by design.

## `projects/<projectId>/hardware.json` — private hardware sources and hints

**Status:** approved contract for SOLUSDEV-251, ADR-034 amendment 2026-09-07. This section
specifies the new file before its consumers are implemented. It does not change existing
`projects.json`, extension, preference or chat-cache shapes.

```json
{
  "schema_version": 1,
  "accounts": {
    "00000000-0000-4000-8000-000000000001": {
      "sources": {
        "00000000-0000-4000-8000-000000000002": {
          "path": "/workspace/calibration.json",
          "contentSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        }
      },
      "bindings": {
        "00000000-0000-4000-8000-000000000003": {
          "lastSeenPath": "/dev/example-port"
        }
      }
    }
  }
}
```

| Field                       | Contract                                                                                                                                            |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema_version`            | Required literal integer `1`; booleans are invalid.                                                                                                 |
| `accounts`                  | Required map, at most 16 entries; keys are authenticated user UUIDs.                                                                                |
| `sources`                   | Required map per account, at most 256 entries; keys are opaque source-reference UUIDs.                                                              |
| `sources[id].path`          | Required absolute POSIX or Windows path, 1–4096 characters; reject control characters. Absolute-path validation is independent of the parsing host. |
| `sources[id].contentSha256` | Required SHA-256 of the selected bytes, exactly 64 lowercase hexadecimal characters.                                                                |
| `bindings`                  | Required map per account, at most 256 entries; keys are configuration-entry UUIDs.                                                                  |
| `bindings[id].lastSeenPath` | Optional port hint, at most 512 characters; reject control characters. An empty binding object is valid.                                            |

All UUID map keys use the canonical hyphenated `8-4-4-4-12` hexadecimal shape, including
non-v4 graph IDs. Reject unknown fields at every object level, non-object maps, prototype keys,
wrong scalar types, nonfinite numbers and files exceeding **256 KiB of UTF-8 JSON bytes**.
Limits are rejection boundaries, never silent truncation. The empty document is
`{"schema_version":1,"accounts":{}}`.

**Contract twins:** `packages/shared-types/src/hardware-local-state.ts` exports
`HARDWARE_LOCAL_STATE_SCHEMA_VERSION`, `HARDWARE_LOCAL_STATE_FILENAME`,
`HARDWARE_LOCAL_STATE_MAX_BYTES`, `HardwareLocalSource`, `HardwareLocalBinding`,
`HardwareLocalAccount`, `HardwareLocalState`, `parseHardwareLocalState` and
`emptyHardwareLocalState`. The Python twin is
`packages/contracts/python/solus_contracts/hardware_local_state.py`, with identical wire aliases
(`contentSha256`, `lastSeenPath`) and bounds. Fixtures live in
`packages/shared-types/fixtures/hardware-local-state/` and are exercised from both languages.

The TypeScript parser returns `{ok:true,state}` or `{ok:false,reason:"invalid"|"newer"}`.
A structurally recognizable future positive integer schema version returns `newer`, even when
it contains unknown future fields. Python strict validation rejects invalid/newer documents;
the local reader distinguishes the version before treating the file as relink-required.
A newer version is read-only. Corruption produces an explicit relink state: do not erase it or
automatically write an empty file. Absence permits a new empty document. Explicit user relinking
can replace corrupt state only through the validated MAIN workflow.

**Ownership and trust:** desktop MAIN alone writes the file through sender-gated, authenticated
project/account picker or import operations. A renderer or remote request cannot authorize an
arbitrary path by naming it. MAIN stores the canonical selected path and digest, validates
symlink/canonical-path changes when reopening, and writes atomically through a same-directory
temporary file and rename. File mode is 0600; all containing Solus directories are 0700. Validate
before write and again before read. The local hardware runner resolves only the authenticated
project/account's opaque reference and verifies its selected bytes and digest before parsing.
A changed digest requires a newly reviewed proposal. The cloud has no local-file reader.

The document is never synced, sent to the API as configuration, placed in shared history or
included in model context. It contains no calibration values, capabilities, graph ownership,
credentials, server-owned settings or durable permission to reconnect an ambiguous endpoint.
Portable configuration records the opaque source reference and verified values; a private path
is not provenance in the shared document. A saved port hint never establishes device identity,
and detachment expires serial-less or duplicate-device selection.

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
7. **Corrupt files never crash a reader**. Registry/cache parse failures degrade as specified
   above. The hardware source/hint file is an exception: corruption requires explicit relinking
   and must not be automatically overwritten. Newer files are always protected.

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
