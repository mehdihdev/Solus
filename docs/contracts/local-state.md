# Local State — machine-local files under `~/.solus`

**Ratified:** in-session at the SOLUSDEV-166 MR (ADR-034). Design: `docs/architecture/solus-folder.md`.
**Shapes:** `packages/shared-types/src/local-state.ts` (TypeScript) ·
`packages/contracts/python/solus_contracts/local_state.py` (Python).
**Fixtures:** `packages/shared-types/fixtures/local-state/` — validated by BOTH suites; the
`_fields.json` manifest is regenerated from the pydantic serialization aliases
(`packages/companion/tests/test_local_state_contract.py`) and checked by the TS field lists.

## What this contract covers

The machine-local, private, never-synced layer of ADR-034: files under `~/.solus/` on the user's
computer. The team-shared repo `.solus/` layer (TOML) is a separate, later contract.

| Path                      | Contents                                     | Writer               | Readers                 |
| ------------------------- | -------------------------------------------- | -------------------- | ----------------------- |
| `~/.solus/companion_id`   | 32-hex machine identity (pre-dates this)     | companion            | companion               |
| `~/.solus/projects.json`  | `ProjectRegistry` — project→working-copy     | desktop MAIN process | desktop main, companion |
| `~/.solus/config.json`    | machine prefs — **reserved**, schema TBD     | —                    | —                       |
| `~/.solus/projects/<id>/` | per-project overrides + cache — **reserved** | —                    | —                       |
| `~/.solus/logs/`          | log files — **reserved** (Ticket E)          | —                    | —                       |

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
- **Companion**: today only `companion_id`; later tickets may read `projects.json` via
  `solus_contracts.local_state`.
