# Cowork QA — SOLUSDEV-147: Unify .env file system

Test plan for the single source-of-truth env system. You need only a checkout of the
`SOLUSDEV-147-env-consolidation` branch, Node ≥ 22, and pnpm. **Do not commit any
`.env.mega` you create** — it is gitignored on purpose.

## Setup

1. `git checkout SOLUSDEV-147-env-consolidation`
2. `node --version` → 22.x or newer; `pnpm --version` → 9.x.
3. Before you start, note whether real env files exist (`.aws.env` was removed in
   SOLUSDEV-152):
   `ls -la apps/desktop/.env apps/desktop/.env.claude packages/api/.env packages/api/.env.claude`
   If you have real secrets in them, **back them up** (`cp .env .env.bak`) — `sync`
   overwrites them.

> Safety tip: to exercise everything without touching real files, run the CLI against a
> throwaround dir: `ENV_SYNC_ROOT=/tmp/envqa node scripts/env-sync.mjs <cmd>` and put
> fixture files under `/tmp/envqa`.

## Path 1 — Unit/integration test suite

- [ ] `pnpm test:env` → all tests pass (29), 0 failures.
- [ ] `pnpm test` → workspace tests plus env tests run and pass.

## Path 2 — Template is present and secret-free

- [ ] `cat env.mega.example` shows blocks for `apps/desktop/.env`,
      `apps/desktop/.env.claude`, `apps/web/.env`, `packages/api/.env`,
      `packages/api/.env.claude`, and a `# >>> common` block. (The `.aws.env`
      block was removed in SOLUSDEV-152 — GitLab CI variables, not in-repo env.)
- [ ] No real secret values appear in `env.mega.example` (all secret RHS are blank).
- [ ] `git check-ignore env.mega.example` prints **nothing** (it is tracked).

## Path 3 — Happy path: fill mega, sync

1. `cp env.mega.example .env.mega`
2. Edit `.env.mega`: set `SUPABASE_URL=https://demo.supabase.co`,
   `SUPABASE_ANON_KEY=anon123`, `SUPABASE_JWT_SECRET=jwt123`, and
   `SOLUS_DATABASE_URL=postgres://demo`.
3. `pnpm env:sync`
   - [ ] Output lists each of the 5 files with a key count and **key names only** —
         no values like `anon123` or `jwt123` appear anywhere in the output.
   - [ ] `cat apps/desktop/.env` → `VITE_SUPABASE_URL=https://demo.supabase.co` and
         `VITE_SUPABASE_ANON_KEY=anon123` (the `${...}` references resolved from common).
   - [ ] `cat packages/api/.env.claude` → `SOLUS_SUPABASE_JWT_SECRET=jwt123` (shared
         secret filled once in common, appears in both api files).

- [ ] `git check-ignore .env.mega` prints `.env.mega` (secrets stay out of git).

## Path 4 — Bootstrap: gather from existing files

1. Remove the mega: `rm -f .env.mega`
2. Ensure at least one target exists (Path 3 created them).
3. `pnpm env:gather`
   - [ ] Output lists each existing file gathered (key counts), skips any missing file.
   - [ ] `.env.mega` now exists with a `# >>> <path>` block per file and the values
         from those files.
4. `pnpm env:sync` again → [ ] regenerates the targets with no errors (round-trip works).

## Path 5 — Guards & failure paths

- [ ] **Clobber guard:** with a `.env.mega` present, `pnpm env:gather` → fails with
      "already exists"; the existing `.env.mega` is unchanged.
- [ ] **Force:** `pnpm env:gather --force` → overwrites `.env.mega`.
- [ ] **Missing mega:** `rm -f .env.mega && pnpm env:sync` → clear error telling you to
      run `env:gather` or copy the example. Exit code non-zero (`echo $?` → 1).
- [ ] **Drift/loss warning:** add a stray key to a target
      (`echo 'SOLUS_LEGACY=x' >> packages/api/.env`), then `pnpm env:sync` → output
      warns that `SOLUS_LEGACY` exists in the target but not the mega and will be dropped;
      after sync the key is gone.
- [ ] **Unresolved reference:** put `FOO=${NOPE}` under a block in `.env.mega` and run
      `pnpm env:sync` → fails naming `NOPE`; no partial/garbage files written for it.
- [ ] **Unknown command:** `node scripts/env-sync.mjs frobnicate` → "unknown command".

## Path 6 — Security spot-checks (§7)

- [ ] Re-run `pnpm env:sync` with real-looking secrets in `.env.mega` and confirm **no
      secret value** is printed to the terminal (only keys/paths).
- [ ] Put `# >>> ../escape.env` as a block header in `.env.mega`, run `pnpm env:sync` →
      refuses with "outside the repo"; confirm no `../escape.env` was created.

## Path 7 — Onboarding message

- [ ] Temporarily move `packages/api/.env` aside and run `pnpm dev:all` (or read
      `scripts/dev-all.sh`) → the missing-env message points at
      `cp env.mega.example .env.mega` / `pnpm env:sync` (not the old nonexistent
      `.env.example`). Restore your file afterward.

## Cross-feature

- [ ] After a full `env:sync`, `pnpm dev:all` starts the stack using the generated files
      (API reads `packages/api/.env`, desktop reads `apps/desktop/.env`) — no regression
      vs. hand-maintained env files.

## Cleanup

- [ ] Restore any backed-up real env files (`mv .env.bak .env`).
- [ ] Delete any throwaway `.env.mega` if you don't intend to use it. Never commit it.
