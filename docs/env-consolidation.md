# Environment Configuration Convention (SOLUSDEV-147)

> **For the human:** copy the section between the two `--- CUT ---` markers into the
> root `CLAUDE.md` — a good home is right after §4 (Technology Stack). Agents cannot
> edit `CLAUDE.md` themselves (hook H1 blocks it), so this file is the drop-in source.
>
> The tooling this describes is implemented on branch `SOLUSDEV-147-env-consolidation`
> (`scripts/env-sync.mjs`, `scripts/lib/env-mega.mjs`, `env.mega.example`, the
> `pnpm env:sync` / `pnpm env:gather` scripts). Once merged, this convention is live.

--- CUT ---

## Environment Configuration — single source of truth

There is **one** environment file a developer fills in: **`.env.mega`** at the repo
root (gitignored — it holds secrets). Every per-package env file is _generated_ from
it by `pnpm env:sync`. Never hand-edit a generated file, and never introduce a new
standalone `.env` that isn't fed by `.env.mega`.

### Generated files (outputs — do not edit by hand)

| Generated file             | Keys                                                                  | Notes                                 |
| -------------------------- | --------------------------------------------------------------------- | ------------------------------------- |
| `.aws.env`                 | `AWS_*`, `ECR_*`, `ECS_*`, `DB_SECRET_ARN`, `EXEC_ROLE`, `INFRA_ROLE` | AWS deploy config                     |
| `apps/desktop/.env`        | `VITE_*`                                                              | Desktop dev profile                   |
| `apps/desktop/.env.claude` | `VITE_*`                                                              | Agent-run profile (values may differ) |
| `packages/api/.env`        | `SOLUS_*`                                                             | API dev profile                       |
| `packages/api/.env.claude` | `SOLUS_*`                                                             | Agent-run profile (superset of keys)  |

### Mega file format

`.env.mega` is split into blocks by `# >>> <path>` headers; each block's `KEY=VALUE`
lines are written verbatim to that path. A `# >>> common` block is **not** written to
any file — it exists only so shared secrets can be defined once and referenced via
`${VAR}` interpolation in later blocks. Bare and `"double-quoted"` values interpolate
`${VAR}`; `'single-quoted'` values are literal. A space before `#` starts an inline
comment.

```dotenv
# >>> common            (not written; for ${} reuse only)
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_JWT_SECRET=...

# >>> apps/desktop/.env
VITE_SUPABASE_URL=${SUPABASE_URL}
VITE_API_BASE_URL=http://127.0.0.1:8000

# >>> packages/api/.env
SOLUS_DATABASE_URL=postgres://...
SOLUS_SUPABASE_JWT_SECRET=${SUPABASE_JWT_SECRET}
```

The committed template `env.mega.example` documents every key with blank/placeholder
values (no secrets). Update it whenever a new env var is introduced.

### Commands

- **`pnpm env:gather`** — one-time bootstrap. Reads the existing env files — the repo
  root `.env`, `.aws.env`, and the per-package `.env` / `.env.claude` files — and
  writes `.env.mega` from their current values, so you never retype secrets you
  already have. Refuses to overwrite an existing `.env.mega` without `--force`.
- **`pnpm env:sync`** — the normal forward direction. Reads `.env.mega` and regenerates
  every target file (`.env.mega` is authoritative — a full overwrite). Logs the files
  and **key names** written, never values (CLAUDE.md §7). Warns before overwriting if a
  target holds keys absent from `.env.mega`, so secrets are not silently dropped.

Onboarding: `cp env.mega.example .env.mega`, fill it in, `pnpm env:sync`.

### Rules for agents

- Adding a new environment variable means adding the key to `env.mega.example` (and
  noting it in your MR) — not editing a generated `.env` file.
- Agents cannot read or write any `.env*` file (hooks H1/read_hook block it, correctly).
  The `pnpm env:*` scripts are run by a human and do the file I/O; the env tooling lives
  in `scripts/` (plain files, never `.env*`).
- No secret values in source, logs, tests, or fixtures — ever (CLAUDE.md §7).

### Known limitations

- Generated values containing a literal `$` used by Vite (which expands `$VAR`) may need
  manual single-quoting in the target; the sync serializer double-quotes but does not
  escape `$`. None of the current keys hit this.
- `.aws.env` is regenerated without an `export` prefix. If a workflow relies on
  `source .aws.env` exporting vars, use `set -a; source .aws.env; set +a`.

--- CUT ---
