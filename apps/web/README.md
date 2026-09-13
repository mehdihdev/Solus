# @solus/web

The Solus marketing site: a single landing page with waitlist capture.

This app is **deliberately self-contained**. It does not import from
`packages/api`, `packages/shared-types`, or any other workspace package, and it
talks to no Solus service. Its only backend dependency is the Google Sheets API.
That keeps it deployable to Vercel on its own, independent of the Solus API's
release cycle.

## Local development

```bash
pnpm install            # from the repo root
pnpm --filter @solus/web dev
```

`next.config.mjs` loads the repo-root `.env` when it exists, so local runs pick
up the same file as the rest of the monorepo. Real environment variables always
win, which is what makes Vercel's injected config authoritative in production.

```bash
pnpm --filter @solus/web test     # node:test, no extra dependencies
pnpm --filter @solus/web build
```

## Waitlist → Google Sheets

`POST /api/waitlist` appends one row per signup to a Google Sheet.

| Column | Value                       |
| ------ | --------------------------- |
| A      | email (trimmed, lowercased) |
| B      | ISO 8601 timestamp          |
| C      | source (`landing-page`)     |

### Environment variables

Set these in the Vercel project (and in the repo-root `.env` for local runs).
They are also listed in the root `env.example`.

| Variable                             | Required | Notes                                                                                    |
| ------------------------------------ | -------- | ---------------------------------------------------------------------------------------- |
| `GOOGLE_SHEETS_SPREADSHEET_ID`       | yes      | The ID from the sheet URL, between `/d/` and `/edit`.                                    |
| `GOOGLE_SERVICE_ACCOUNT_JSON`        | yes\*    | The whole service-account JSON key, pasted as one value.                                 |
| `GOOGLE_SERVICE_ACCOUNT_EMAIL`       | yes\*    | Alternative to the JSON blob: the `client_email` field.                                  |
| `GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY` | yes\*    | Alternative to the JSON blob: the `private_key` field. Literal `\n` escapes are handled. |
| `GOOGLE_SHEETS_RANGE`                | no       | Defaults to `Waitlist!A:C`. The tab name must match.                                     |

\* Supply **either** `GOOGLE_SERVICE_ACCOUNT_JSON` **or** the email/private-key
pair. The JSON blob is preferred — it is one value and cannot drift.

If configuration is missing, the route returns a generic 500 to the browser and
logs exactly which variables are absent, so the cause is visible in the Vercel
function logs without exposing anything to the caller.

### Abuse controls

- **Honeypot** — an off-screen `company` field. Filled means bot: the route
  answers 200 and writes nothing, so the bot cannot tell it was caught.
- **Rate limit** — 5 requests per IP per 10 minutes, returning 429 with
  `Retry-After`. The counter is in-process, so on serverless it is per warm
  instance rather than global. It blunts a burst from one client; it is not a
  defence against a distributed attack. To make it authoritative, swap
  `lib/waitlist/rate-limit.js` for a Redis-backed implementation.
- **Size cap** — request bodies over 2 KB are rejected unread.
- **Formula injection** — rows are written with `valueInputOption: "RAW"`, so an
  address beginning `=`, `+`, `-` or `@` is stored as text and never evaluated
  by Sheets.

## Deploying to Vercel

`vercel.json` in this directory carries the install command, so the only things
to set by hand are the Root Directory and the environment variables.

1. **New Project** → import this repository (GitLab). The branch must be pushed
   first; Vercel deploys from the remote, not your working copy.
2. **Root Directory**: `apps/web`. Leave "Include files outside the root
   directory" **enabled** — the pnpm lockfile lives at the repo root.
3. **Environment Variables**: add the table above for Production, Preview and
   Development.
4. Deploy, then submit a real address and confirm the row lands in the sheet.

Everything else is picked up automatically: framework preset (Next.js), build
command (`next build`), and Node 22 via `engines.node` in `package.json`.

### Why the install command is overridden

This repo sets `node-linker=hoisted` in `.npmrc`, and a plain `pnpm install`
from `apps/web` resolves the **whole** workspace — all four projects, ~980
packages, 1.3 GB, including a 272 MB Electron binary that the marketing site has
no use for. `--filter` alone does not prune it, because the hoisted linker
builds one tree for the entire workspace.

Pairing the filter with `--node-linker=isolated` does prune it: 381 packages, no
Electron, and `next build` and `next start` both verified against a clean clone.

### Deploying without the Git integration

To push a build straight from a working copy:

```bash
cd apps/web
npx vercel --prod
```

This uploads the directory as-is and does not read the repo-root lockfile, so
Vercel resolves dependencies from `package.json` alone. Use it for a one-off;
prefer the Git integration for anything ongoing.

### Dependency weight

The app ships four runtime dependencies: `next`, `react`, `react-dom` and
`@googleapis/sheets` (~620 KB — the Sheets-only client, rather than the umbrella
`googleapis` package at ~194 MB). Nothing else is needed to build or serve the
site.
