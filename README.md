# Solus

Solus is a cross-domain development workspace for robotics teams. It builds a unified graph — the Robotics Context Model — across the tools a team already uses (GitHub, GitLab, KiCad, Onshape, ROS), then reasons over that graph to catch cross-domain problems before they break the robot.

See [`CLAUDE.md`](./CLAUDE.md) for how development works in this repository.

## Prerequisites

Docker · [`uv`](https://docs.astral.sh/uv/) · pnpm · Node ≥ 22
· [Stripe CLI](https://docs.stripe.com/stripe-cli) (billing only)

## Setup

```bash
make bootstrap          # corepack + pnpm install + uv sync + git hooks
cp env.example .env     # then fill it in — see below
make db-up              # Postgres + Redis in Docker
cd packages/api && uv run alembic upgrade head && cd -
```

### Env — there is exactly one file

**`.env` at the repo root, and nothing else.** Every process reads it directly:

| Consumer                | How it finds the root `.env`                                             |
| ----------------------- | ------------------------------------------------------------------------ |
| FastAPI backend         | `env_file` anchored to the repo root (`packages/api/.../core/config.py`) |
| Desktop (Electron/Vite) | `envDir` → repo root (`apps/desktop/electron.vite.config.ts`)            |
| Web (Next)              | `process.loadEnvFile` (`apps/web/next.config.mjs`)                       |

Each reads only what it recognises — the backend takes `SOLUS_*`, Vite exposes only
`VITE_*` to the renderer bundle, the waitlist route reads `GOOGLE_*`. Real environment
variables always win over the file.

> **Do not create per-package `.env` files.** They used to exist, and a stale one
> shadowing the root file — a blank value beating a good one — was a recurring source of
> "works for me" breakage. If you find `packages/api/.env`, `apps/desktop/.env` or
> `apps/web/.env`, delete it.

Values are literal; there is no `${VAR}` expansion. `env.example` documents every key.

An authentication key required for startup is **`SOLUS_SUPABASE_JWT_SECRET`** (Supabase dashboard →
Project Settings → API → JWT Secret); without it the API exits immediately. For real
sign-in also set `SOLUS_SUPABASE_URL`, plus `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`
for the **same** project. Without those the desktop app runs a dev-bypass login: the UI
looks authenticated and every API call returns 401.

Set `SOLUS_SECRETS_KEY` (a Fernet key — the generator is in `env.example`) before anything
that stores credentials. Without it the secret store is in-memory and every OAuth token and
provider key is lost on each reload.

## Run

```bash
pnpm dev:all            # Postgres + configured Redis + API + desktop/companion + optional Stripe
```

The launcher checks the selected database schema and configured Redis before starting the
API, then waits for API readiness before opening the desktop. It never runs migrations or
installs dependencies on startup. Run `make bootstrap` and `make mcp-forks` once after cloning;
after schema changes, back up existing data and run the Alembic command from Setup.
Ctrl+C stops only this launch's application processes; Docker data and services remain available.
The selected Node executable (including nvm Node ≥ 22) is pinned for API-side MCP tools.
When Redis is configured, this launcher defaults remote source syncs to its background worker,
overriding the legacy `.env` inline setting so long Onshape imports can survive API reloads.
Local-folder, KiCad and Altium acquisition runs in API background tasks because their
desktop bridge belongs to that process; these tasks are still interrupted by API reloads.
An explicit shell `SOLUS_SYNC_INLINE` value takes precedence; Redis-disabled launches
retain their existing configuration.

Compose defaults to a volume scoped to this checkout's project name. To reuse a known existing
local database, create the gitignored `docker-compose.local.yml` before starting:

```yaml
volumes:
  solus-pgdata:
    external: true
    name: YOUR_EXISTING_VOLUME_NAME
```

Inspect the existing container's mounts first, back up its database, and stop that container
before attaching its volume to another PostgreSQL container. Never delete volumes to fix
startup. The launcher includes this override in every Compose operation. Manual Compose
commands for this selection must include both `-f docker-compose.dev.yml` and
`-f docker-compose.local.yml`; plain `make db-up` does not load the local override.
External database/Redis URLs remain external; only configured default loopback dependencies
are started in Compose. Configured services owned by another checkout are refused.

Local MCP tools require the Electron desktop, a signed-in selected project, and a linked
folder under Home → Local folder for workspace operations. KiCad's fork is installed by
`make mcp-forks`; native CLI operations also need KiCad installed. Fusion is a separate
vendor-run server: open Fusion and enable Preferences → General → API → Fusion MCP Server
(port 27182). A missing native app/server remains unavailable; installing Python forks cannot
start Fusion. See `integrations/mcp/README.md` for tool prerequisites.

Individual pieces:

| Command                                 | What                                                          |
| --------------------------------------- | ------------------------------------------------------------- |
| `make db-up` / `make db-down`           | Postgres **and** Redis, waits until both healthy              |
| `pnpm db:up`                            | Postgres only — Redis stays down, so rate limiting fails open |
| `make dev-api` / `pnpm dev:api`         | backend only (`:8000`, docs at `/api/v1/docs`)                |
| `make mcp-forks`                        | install the vendored MCP forks' venvs (once; hash-verified)   |
| `make dev-desktop` / `pnpm dev:desktop` | Electron app only                                             |
| `make dev-web` / `pnpm dev:web`         | marketing site                                                |
| `pnpm dev:stripe`                       | Stripe webhook forwarder only                                 |

Check the API is healthy: `curl localhost:8000/readyz` → `database: ok`, and
`redis: configured` once `SOLUS_REDIS_URL` is set.

### When the stack won't start

| Symptom                                        | Cause and fix                                                                                                                                                                                     |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[Errno 98] Address already in use`            | An earlier API was orphaned and still owns `:8000` — closing its terminal does not kill it. `ss -ltnp "sport = :8000"`, then `kill <pid>`. `pnpm dev:all` now refuses to start and names it.      |
| `relation "…" does not exist` on some routes   | Your dev DB is behind the repo after a merge: `cd packages/api && uv run alembic upgrade head`.                                                                                                   |
| Routes 404/500 only for a newly merged feature | Same as above — migrate. Keep `SOLUS_AUTO_CREATE_TABLES=false`: creating tables at startup skips Alembic, so `alembic_version` goes stale and the next `upgrade head` fails on an existing table. |

An orphaned API is worse than a busy port: with no `--reload` it keeps serving whatever code was
checked out when it started, so the app can look "broken" long after the fix is merged. If the
process holding `:8000` is older than your last `git pull`/merge, kill it. Don't reach for
`pkill -f uvicorn` — with `--reload` the worker shows up as a bare `python3`, so that pattern
misses the process actually holding the port while matching things you didn't mean.

### LLM provider keys

Provider and tool keys are **not** read from env at request time — the code reads them from
the secret store. Put `ANTHROPIC_API_KEY` (and/or `OPENAI_API_KEY`, `GOOGLE_API_KEY` /
`GEMINI_API_KEY`, `BRAVE_API_KEY`) in `.env`, then run once:

```bash
make seed-secrets
```

Skip it and every SOL turn fails with `ProviderCredentialsMissingError`, and web search
stays `UNAUTHORIZED`.

## Billing (Stripe)

The Stripe **secret key lives in the database**, not in env — so re-run `put-key` whenever
you recreate the dev database. Requires `SOLUS_SECRETS_KEY` to be set first.

```bash
stripe login
uv run stripe-setup put-key     # interactive; stores sk_test_... encrypted
uv run stripe-setup bootstrap   # creates test Prices, prints two .env lines
#   → paste SOLUS_STRIPE_PLAN_PRICES / SOLUS_STRIPE_PACK_CREDITS into .env, restart the API
uv run stripe-setup check       # must print "check: PASS"
```

Then run `pnpm dev:all` (or `pnpm dev:stripe`) and pay with test card `4242 4242 4242 4242`.
The webhook signing secret comes from the **Stripe CLI**, not from a dashboard endpoint —
`dev:all` injects it automatically.

When it misbehaves:

| Symptom                                            | Cause                                                        |
| -------------------------------------------------- | ------------------------------------------------------------ |
| `503 billing_unconfigured`                         | no `stripe_api_key` in the secret store, or empty price maps |
| `400 invalid_signature`                            | wrong `whsec_` — dashboard secret used instead of the CLI's  |
| webhook returns `processed: true`, nothing changes | price id isn't in `SOLUS_STRIPE_PLAN_PRICES`                 |

## Quality gates

```bash
make lint          # ruff + eslint
make typecheck     # mypy + tsc
make test          # pytest + vitest + node --test
make gen-openapi   # regenerate openapi.json + desktop types (after model changes)
```
