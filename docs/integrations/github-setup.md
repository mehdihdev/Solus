# GitHub Connector — setup & required env (SOLUSDEV-103)

What you need to do on your end to make "connect my GitHub account and pull a
repo" work end-to-end. The connector framework, GitHub connector, API routes,
and onboarding wiring are implemented; these are the credentials/steps the code
reads at runtime.

> The harness blocks agents from editing `.env*` (it's human-owned), so the
> exact block to paste into `packages/api/.env` (and mirror into
> `packages/api/.env.claude`) is below — copy it in yourself.

## 1. Register a GitHub OAuth App

GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App**.

| Field                      | Value                                  |
| -------------------------- | -------------------------------------- |
| Application name           | `Solus (local dev)`                    |
| Homepage URL               | `http://localhost:5173`                |
| Authorization callback URL | `http://localhost:53682/auth/callback` |

The callback URL above is the **desktop loopback** address the Electron app
listens on (`apps/desktop/src/main/oauthLoopback.ts`, port `53682`). The host must be
`localhost`, not `127.0.0.1`: the connector flow sends `connectorRedirectUrl()` from
`apps/desktop/src/main/oauthCallback.ts`, and GitHub matches the host exactly (SOLUSDEV-216). This is the
flow onboarding uses. After creating the app, click **Generate a new client
secret** and copy the **Client ID** and **Client secret**.

> Web flow (optional): if you also serve the connect flow from a browser rather
> than the desktop app, the API exposes a server-side callback at
> `${SOLUS_PUBLIC_API_BASE_URL}/api/v1/integrations/github/oauth/callback`. A
> single OAuth App has one callback URL, so use a second OAuth App (or a GitHub
> App) for that. Desktop loopback is the default and needs only the row above.

## 2. Generate a local secret-store key

Connector tokens are encrypted at rest. In dev they're Fernet-encrypted into the
DB (`connector_secrets` table); the key comes from the environment. Generate one:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Without `SOLUS_SECRETS_KEY` the API falls back to an in-memory store (tokens are
lost on restart and it logs a warning) — fine for a quick try, not for real use.

In production set `SOLUS_AWS_REGION` (+ IAM access to Secrets Manager) and
`SOLUS_SECRETS_BACKEND=aws` instead; the same code path then uses AWS Secrets
Manager and never touches the DB table.

## 3. Env block — paste into `packages/api/.env`

```bash
# --- Connector framework / GitHub (SOLUSDEV-103) ---

# GitHub OAuth App (step 1)
SOLUS_GITHUB_CLIENT_ID=your-client-id
SOLUS_GITHUB_CLIENT_SECRET=your-client-secret

# Local encrypted secret store (step 2). Omit to use AWS in prod.
SOLUS_SECRETS_KEY=paste-the-generated-fernet-key

# Where the *web* OAuth callback redirects back to, and the API's own public
# base (used to build the web callback URL). Safe defaults for local dev:
SOLUS_OAUTH_REDIRECT_APP=http://localhost:5173/#/onboarding
SOLUS_PUBLIC_API_BASE_URL=http://localhost:8000

# Optional: run syncs through the ARQ worker instead of an in-process
# background task. If set, also run the worker (step 4).
# SOLUS_REDIS_URL=redis://localhost:6379/0

# Dev/test convenience: run syncs inline in the request (blocking). Leave unset
# in normal use — without Redis the API uses a non-blocking background task.
# SOLUS_SYNC_INLINE=false

# --- Production secret store (instead of SOLUS_SECRETS_KEY) ---
# SOLUS_AWS_REGION=us-east-1
# SOLUS_SECRETS_BACKEND=aws
```

Renderer side (`apps/desktop`): the existing `VITE_SUPABASE_*` auth env must be
configured (otherwise the app runs in the dev-bypass mode where there's no real
account to attach a token to, and onboarding falls back to the simulated tiles).
`VITE_API_BASE_URL` defaults to `http://localhost:8000/api/v1`.

## 4. (Optional) Run the background worker

Without Redis, a triggered sync runs as an in-process background task — fine for
local use. For scheduled change-detection and queued syncs at scale, set
`SOLUS_REDIS_URL` and run the ARQ worker built by
`solus_api.connectors.worker.build_worker_settings(settings)` (cron sweep +
`sync_source` task). Wiring the `arq` CLI entrypoint is the one remaining glue
step — see the completion report.

## 5. Try it

1. `make db-up` (Postgres) — or use SQLite via `SOLUS_DATABASE_URL` for a quick try.
2. `pnpm dev:api` and `pnpm dev:desktop`.
3. Sign in, reach onboarding, click **Connect** on the GitHub tile → authorize in
   the browser → pick a repo → the sync lands code files (and any committed
   Gerber/STEP/netlist/SPICE exports) as graph entities.

## What lands in the graph

- One `code_repo` entity for the repo, `code_module` for directories, `code_file`
  for files, joined by `contains` relations.
- **Committed design exports (W0-08):** files with Gerber (`.gbr`, `.gtl`, …),
  STEP (`.step`/`.stp`), netlist (`.net`, …), or SPICE (`.cir`, …) extensions are
  surfaced as `design_export` entities (electrical/mechanical domain) for the
  EDA/CAD connectors to parse later.


## GitHub App for team organizations (SOLUSDEV-216, ADR-039)

Linking an organization to a Solus team uses a **GitHub App**, which is separate from the OAuth App above. Register one App per environment: dev, staging and prod.

GitHub → **Settings → Developer settings → GitHub Apps → New GitHub App**. For a company-owned App, register it under the Solus org's own settings instead.

| Field | Value |
|---|---|
| GitHub App name | `Solus` (or `Solus (dev)`). The slug becomes `SOLUS_GITHUB_APP_SLUG` |
| Homepage URL | `https://solus.dev` (anything public) |
| Callback URL(s) | `http://localhost:53682/auth/callback` (desktop loopback). Add the API host's URL for web later. |
| Expire user authorization tokens | ✅ on. Solus uses the user token only once, at install, and never stores it |
| **Request user authorization (OAuth) during installation** | ✅ **required**. It gives the `code` that proves the installer can access the installation (ADR-039 §2) |
| Enable Device Flow | off |
| Setup URL | leave empty. With the box above checked, GitHub redirects to the callback URL |
| Redirect on update | ✅ on |
| Webhook → Active | ✅ |
| Webhook URL | `${SOLUS_PUBLIC_API_BASE_URL}/api/v1/webhooks/github/app`. It must be public HTTPS. For local dev, use a tunnel (`cloudflared` / `ngrok`) or leave inactive; the hourly sweep still syncs |
| Webhook secret | A random 32+ byte string becomes `SOLUS_GITHUB_APP_WEBHOOK_SECRET`. Generate it with `openssl rand -hex 32` |
| SSL verification | Enabled |

**Permissions.** Read-only, and nothing else. ADR-039 §9 requires a new ADR for any write permission.

| Scope | Permission | Access |
|---|---|---|
| Repository | Contents | Read-only |
| Repository | Metadata | Read-only (mandatory) |
| Organization | Members | Read-only |

**Subscribe to events:**
- Push
- Repository
- Organization
- Member

`installation` and `installation_repositories` are always delivered, so they don't need a checkbox.

**Where can this GitHub App be installed?** Choose **Any account**. Customers install it on their own orgs.

After creating the App:
1. Note the **App ID** and the **Client ID**.
2. Click **Generate a new client secret**.
3. Under *Private keys*, click **Generate a private key**. This downloads a `.pem`. Keep it out of the repo.

### Env block for the App (paste into `packages/api/.env`; in prod, use Secrets Manager)

```bash
# --- GitHub App: team organizations (SOLUSDEV-216) ---
SOLUS_GITHUB_APP_ID=123456
SOLUS_GITHUB_APP_SLUG=solus-dev
SOLUS_GITHUB_APP_CLIENT_ID=Iv23li...
SOLUS_GITHUB_APP_CLIENT_SECRET=...
SOLUS_GITHUB_APP_WEBHOOK_SECRET=...
# The PEM on one line with literal \n escapes, OR a path via SOLUS_GITHUB_APP_PRIVATE_KEY_PATH
SOLUS_GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n"
```

If any of these is missing, the org feature reports `github_app_unconfigured` and stays hidden. The OAuth App flow above keeps working regardless.

### Try it

1. Create a test org on GitHub with one or two private repos.
2. In Solus, open a collaborative team → Home → **GITHUB ORGANIZATION** → **Link organization**.
3. Install the App on the test org, then approve the authorization.
4. A second team member opens a project → Connect → GitHub, and picks a repo under the org section. They need no GitHub sign-in.
5. Push to that repo. With a public webhook URL, a sync starts within seconds.
