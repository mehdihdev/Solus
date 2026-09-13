# @solus/web

The Solus marketing site: landing page, waitlist capture, and blog.

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

1. **New Project** → import this repository.
2. **Root Directory**: `apps/web`. Leave "Include files outside the root
   directory" enabled so pnpm can resolve the workspace lockfile.
3. **Framework Preset**: Next.js (auto-detected). No build command overrides.
4. **Node.js Version**: 22.x — pinned by `engines.node` in this package.
5. **Environment Variables**: add the table above for Production, Preview and
   Development.
6. Deploy, then submit a real address and confirm the row lands in the sheet.

The waitlist route sets `runtime = "nodejs"`; `googleapis` needs Node APIs and
will not run on the edge runtime.
