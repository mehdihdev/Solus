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

`pnpm env:sync` writes the **entire** resolved `.env.mega` verbatim into every file
below — there is no per-file key routing. Each consumer reads only the keys it
recognises; extra keys are ignored and harmless.

| Generated file      | Keys it reads          | Read by                                          |
| ------------------- | ---------------------- | ------------------------------------------------ |
| `.env`              | `DB_*`, `REDIS_URL`, … | repo-root tooling / docker-compose               |
| `apps/desktop/.env` | `VITE_*`               | Electron renderer (Vite exposes only `VITE_*`)   |
| `apps/web/.env`     | `GOOGLE_*`             | Next.js waitlist route                           |
| `packages/api/.env` | `SOLUS_*`              | FastAPI backend (pydantic `env_prefix="SOLUS_"`) |

Every generated file is a byte-identical copy of the resolved mega. Dropped vs the
earlier block model (SOLUSDEV-164): the `.env.claude` agent-run profiles (whole-file
sync makes them identical to `.env`, and no code reads them) and `.aws.env` (deploy
vars are GitLab CI-scoped variables — the `AWS_*`/`ECR_*`/`ECS_*` keys still live in
the mega for ops scripts, they just aren't routed to a dedicated file).

### Mega file format

`.env.mega` is a **flat** `KEY=VALUE` list — no routing headers. Every key is emitted
to every target; define a shared value once and reference it later with `${VAR}` (a key
may reference any earlier key). Bare and `"double-quoted"` values interpolate `${VAR}`;
`'single-quoted'` values are literal. A space before `#` starts an inline comment. Any
line starting with `#` is a comment (a legacy `# >>> path` header is ignored, so old
mega files still parse).

```dotenv
# shared values, defined once
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_JWT_SECRET=...
DB_USER=solus
DB_PASSWORD=solus

# desktop reads VITE_*
VITE_SUPABASE_URL=${SUPABASE_URL}
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1

# backend reads SOLUS_* (env_prefix is unchanged, so the prefix must stay here)
SOLUS_DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@localhost:5432/solus
SOLUS_SUPABASE_JWT_SECRET=${SUPABASE_JWT_SECRET}
```

The committed template `env.mega.example` documents every key with blank/placeholder
values (no secrets). Update it whenever a new env var is introduced.

### Commands

- **`pnpm env:gather`** — one-time bootstrap. Reads the existing target files (repo-root
  `.env`, `apps/desktop/.env`, `apps/web/.env`, `packages/api/.env`), merges their keys
  into one flat `.env.mega` (first file wins on duplicates; divergent values are flagged
  by key name), so you never retype secrets you already have. Refuses to overwrite an
  existing `.env.mega` without `--force`.
- **`pnpm env:sync`** — the normal forward direction. Reads `.env.mega`, resolves
  `${VAR}` interpolation, and writes the whole result into every target file (`.env.mega`
  is authoritative — a full overwrite). Logs the files and **key names** written, never
  values (CLAUDE.md §7). Warns before overwriting if a target holds keys absent from
  `.env.mega`, so secrets are not silently dropped.

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
- Because the whole mega is written to every file, secret values (e.g. the DB password,
  the JWT secret) appear in all four generated files, not just the one that consumes
  them. All four are gitignored; this is the accepted trade-off of the whole-file model.
- The prefixes matter: the backend still reads `SOLUS_*` and Vite still exposes `VITE_*`,
  so those prefixes must be present on the keys in `.env.mega`. Renaming a `SOLUS_`/
  `VITE_` key without a matching code change makes that key invisible to its consumer.

--- CUT ---
