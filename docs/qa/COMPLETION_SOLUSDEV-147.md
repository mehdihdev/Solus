# Completion Report — SOLUSDEV-147: Unify .env file system

**Branch:** `SOLUSDEV-147-env-consolidation` (off `main`)
**Ticket:** [SOLUSDEV-147](https://solusforge.atlassian.net/browse/SOLUSDEV-147) — "Unify .env file system"
**Status:** Integrated on the feature branch, full validation green, ready for human review/push/MR.

## What was built

A single source-of-truth env system. Developers fill in **one** file, `.env.mega`
(gitignored), and `pnpm env:sync` regenerates every per-package env file from it.

- **`scripts/lib/env-mega.mjs`** — pure, FS-free parser/renderer:
  - `parseMega` — split `.env.mega` into `# >>> <path>` blocks.
  - `splitToTargets` — resolve `${VAR}` interpolation (against a `# >>> common`
    block + earlier keys in the same block) and serialize each target file.
  - `parseEnvFile` — read existing `.env` files (tolerates `export`, quotes).
  - `serializeEntries` / `renderMega` — safe serialization for target files and
    for the mega file respectively.
  - `diffKeys` — drift/loss guard.
- **`scripts/env-sync.mjs`** — the CLI (run by a human via pnpm):
  - `sync`: `.env.mega` → the 5 target files (full overwrite; source of truth).
    Warns before dropping keys that exist in a target but not the mega. Logs paths
    and **key names only — never values** (§7). Refuses paths escaping the repo root.
  - `gather`: existing files → `.env.mega` (one-time bootstrap). Refuses to clobber
    an existing `.env.mega` without `--force`.
- **`env.mega.example`** — committed template (no secrets) documenting every key.
- **`package.json`** — `env:sync`, `env:gather`, `test:env` scripts; `test` now also
  runs `test:env`.
- **`scripts/dev-all.sh`** — fixed the dangling `cp packages/api/.env.example` message
  (that file never existed) to point at the new `.env.mega` flow.
- **`.prettierignore`** — excludes the unparseable dotenv template.
- **`docs/env-consolidation.md`** — the convention, with a copy-paste block for
  `CLAUDE.md` (agents cannot edit `CLAUDE.md` — hook H1).

Target files driven by the mega (per ticket, includes the `.env.claude` variants):
`.aws.env`, `apps/desktop/.env`, `apps/desktop/.env.claude`, `packages/api/.env`,
`packages/api/.env.claude`.

## Governing docs consulted

- CLAUDE.md §5 (branch discipline — own ticket/branch), §7 (no secret values in
  logs/source; path-traversal guard), §8 (coding standards), §6 (TDD).
- No architecture/API/wireflow doc governs this (pure tooling); DECISIONS.md and
  `packages/contracts/` untouched.

## Tests & coverage

- 29 tests (`node --test`, zero new deps): 22 unit (parser/renderer) + 7 integration
  (CLI against a temp tree via `ENV_SYNC_ROOT`).
- Coverage: **99.4% lines** overall (env-sync.mjs 100%, env-mega.mjs 98%). Well above
  the 80% floor. `pnpm test:env` green; eslint + prettier clean.

## Design decisions (delegated judgment)

- **Format = section headers as the path map** (`# >>> <path>`), plus a `common`
  block + `${VAR}` interpolation so shared secrets are filled once. Chosen over a
  separate manifest (KISS, nothing to keep in sync).
- **`.env.claude` included** per the ticket's answer; values may differ per profile,
  which the per-block + `${common}` model handles.
- **Overwrite semantics** for `sync` (mega authoritative), paired with `gather` for
  the initial bootstrap so no secret is retyped.

## Review

- Ran security-reviewer and code-reviewer subagents; both confirmed tests pass and
  found no blocking issues surfaced. Self-review found and fixed one real defect:
  - **[HIGH, fixed]** `serializeMegaValue` originally single-quoted `$`-containing
    values and stripped any `'` (`v.replace(/'/g, "")`) — silent secret corruption on
    `gather`. Replaced with double-quote + `\$` escaping; added the reverse `\$`
    unescape in the parser and a regression test proving a value with both `$` and `'`
    round-trips byte-for-byte.

## Security (§7)

- `.env.mega` is gitignored (`git check-ignore .env.mega` → ignored); `env.mega.example`
  is tracked and contains no secrets.
- CLI logs key names and paths only, never values.
- Path-traversal guard on mega-declared paths (`safeResolve`); tested.
- Agents cannot read/write `.env*` (hooks); the human-run pnpm scripts do the I/O.

## Deviations / open concerns

- **Placeholder branch note:** the ticket number wasn't known when work started, so a
  throwaway `SOLUSDEV-000-env-consolidation` branch was created then deleted; all work
  is on `SOLUSDEV-147-env-consolidation`.
- **`CLAUDE.md` update is a human action** — copy the marked block from
  `docs/env-consolidation.md` into `CLAUDE.md` (hook H1 blocks agent edits).
- **`.aws.env` regenerated without `export`** — if any workflow relies on
  `source .aws.env` exporting vars, use `set -a; source .aws.env; set +a`. Documented
  under "Known limitations".
- **Vite `$` expansion:** target values containing a literal `$` used by Vite may need
  manual single-quoting; none of the current keys hit this. Documented.
