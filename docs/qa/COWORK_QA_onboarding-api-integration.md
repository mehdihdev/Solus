# COWORK QA — Onboarding ↔ API integration (SOLUSDEV-55)

Tests the merged stack: the desktop onboarding app talking to the FastAPI backend, run together with one command. Builds on `COWORK_QA_user-onboarding.md` (the UI flows) — this file covers the **integration** (real auth, real team/project creation, persisted SOL mode, run-as-one) and the offline fallback.

## Setup

Prereqs: Docker, `uv`, pnpm, Node ≥ 22, and a Supabase project (email + GitHub providers enabled).

1. `pnpm install`
2. `cp packages/api/.env.example packages/api/.env` → set `SOLUS_SUPABASE_JWT_SECRET` (Supabase → Project Settings → API → JWT Secret). Leave `SOLUS_AUTO_CREATE_TABLES=true`.
3. `cp apps/desktop/.env.example apps/desktop/.env` → set `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY` for the **same** Supabase project.
4. `pnpm dev:all` — starts Postgres, the API (`:8000`), and the desktop app.

Sanity: open `http://localhost:8000/api/v1/docs` (API up) and `http://localhost:8000/healthz` → `{"data":{"status":"ok"}}`.

To reset a run: `localStorage.clear()` in the app devtools + reload; to reset the DB: `pnpm db:down` then `pnpm db:up` (volume dropped on `down -v`).

## Flow 1 — One-command startup

1. Run `pnpm dev:all` from a clean state. → **Expect:** logs show Postgres starting, then "API on http://127.0.0.1:8000", then the Electron window opens on the Landing page. Ctrl+C stops all three.
2. Omit `packages/api/.env` and run again. → **Expect:** a clear message telling you to create it and set the JWT secret; it does not start half-up.

- [ ] 1.1 `pnpm dev:all` starts DB + API + app; Ctrl+C stops all
- [ ] 1.2 Missing backend .env prints guidance and aborts

## Flow 2 — Real signup → real project (the headline path)

> Email confirmation: if your Supabase project has "Confirm email" enabled, signup now shows a **"Confirm your email"** screen instead of jumping ahead (see Flow 2b). With confirmation disabled, signup goes straight to Onboarding.

1. In the app: Get started → Signup → create an account (or "Continue with GitHub"). → **Expect:** real Supabase signup; lands on Onboarding (About) — or, if confirmation is required, the confirm-email screen (Flow 2b) and then Onboarding.
2. Type a description, e.g. "A 12-DOF quadruped, STM32 firmware". Pick **Expert** SOL mode. Continue → connect ≥2 tools → "Build context model" (or take the template path). → **Expect:** the build animation runs.
3. When build completes, click "Open workspace". → **Expect:** the workspace home shows your project name (derived from the description, e.g. "A 12-DOF quadruped"), your email, "SOL · EXPERT", and a green "LIVE · 0 ENTITIES · 0 RELATIONS · API LINKED" line.
4. **Verify on the backend** (proves it's real, not simulated):
   - `curl http://localhost:8000/api/v1/users/me` with your token, or check Postgres: `docker compose -f docker-compose.dev.yml exec db psql -U solus -d solus -c "select name from projects;"` → your project is there.
   - The user's settings row has `sol_mode = expert`.

- [ ] 2.1 Real Supabase signup reaches onboarding
- [ ] 2.2 Completing onboarding shows the real project name + "API LINKED" on the home
- [ ] 2.3 A `projects` row exists in Postgres with the derived name
- [ ] 2.4 SOL mode persisted server-side as `expert`
- [ ] 2.5 A personal team was auto-created (owner) for the new user

## Flow 2b — Email confirmation auto-continue (requires "Confirm email" ON in Supabase)

1. Sign up with a real email + password. → **Expect:** a "Confirm your email" screen: "We sent a confirmation link to {email}…", a "Waiting for confirmation…" spinner, an "I've confirmed — continue" button, and "Resend confirmation email".
2. Leave the app open. Open your inbox and click the Supabase confirmation link. → **Expect:** within a few seconds (no manual step back in the app), the app signs you in on its own and advances to Onboarding (About).
3. Alternatively, after clicking the link, press "I've confirmed — continue". → **Expect:** immediate sign-in + onboarding.
4. Click "Resend confirmation email". → **Expect:** "Confirmation email re-sent." and a second email arrives.
5. Click "Use a different email". → **Expect:** returns to the signup form with fields editable.
6. Before confirming, confirm the app has **no** session yet (it must not reach onboarding until the link is clicked).

- [ ] 2b.1 Confirm-email screen shown after signup when confirmation is required
- [ ] 2b.2 Clicking the email link auto-continues into onboarding within a few seconds
- [ ] 2b.3 "I've confirmed — continue" signs in immediately
- [ ] 2b.4 Resend sends another email
- [ ] 2b.5 "Use a different email" returns to the form
- [ ] 2b.6 No session/onboarding access before the link is clicked

## Flow 3 — Auth boundary

1. While signed in, confirm API calls carry the token (Network tab: `Authorization: Bearer …` on `/users/me`, `/projects`). → **Expect:** 200s.
2. Sign out, then sign in as a **different** account, complete onboarding. → **Expect:** a separate personal team + project; you never see the first account's project (tenant isolation).
3. Stop the API (`pnpm db:down` / kill the API process) and run onboarding. → **Expect:** the flow still completes (build animates, "Open workspace" works); the home falls back to the simulated summary ("247 NODES …") instead of "API LINKED". No crash, no hang.

- [ ] 3.1 Authenticated requests send the Supabase bearer token
- [ ] 3.2 A second account gets its own team/project; no cross-account leakage
- [ ] 3.3 API down → onboarding degrades gracefully to simulated, no crash

## Flow 4 — Persistence

1. Complete onboarding, then fully reload the app (not just hash nav). → **Expect:** you land on the workspace home; it re-fetches and still shows your project + live stats.
2. `pnpm db:down -v` (drop the volume) then `pnpm db:up`, reload the app. → **Expect:** with `SOLUS_AUTO_CREATE_TABLES=true`, tables are recreated on API start; first `/users/me` re-provisions the user + personal team (a fresh empty DB, so no old project).

- [ ] 4.1 Project + stats survive an app reload
- [ ] 4.2 Fresh DB auto-creates tables and re-provisions on first call

## Flow 5 — GitHub login (loopback OAuth)

**One-time setup (yours to do — needs a GitHub OAuth app + Supabase):**

1. GitHub → Settings → Developer settings → **OAuth Apps** → New OAuth App. Authorization callback URL = `https://<your-project-ref>.supabase.co/auth/v1/callback`. Copy the Client ID + secret.
2. Supabase → Authentication → Providers → **GitHub** → enable, paste the Client ID + secret.
3. Supabase → Authentication → **URL Configuration → Redirect URLs** → add **`http://localhost:53682/auth/callback`** (the desktop loopback; the port is fixed in `apps/desktop/src/main/oauthCallback.ts`).
4. Ensure `apps/desktop/.env` has `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY` for the same project.

> GitHub login only works in the **real Electron app** (`pnpm dev:desktop` / `pnpm dev:all`), not the static browser preview — the loopback listener and system-browser open are main-process features. In the browser preview the button returns "GitHub sign-in is only available in the Solus desktop app." (With no Supabase env at all, the dev bypass still signs you in as a stub.)

**Flow:**

1. On Signup or Login, click **Continue/Sign in with GitHub**. → **Expect:** your system browser opens to GitHub's authorize page; the button stays in "Authorizing with GitHub…".
2. Approve on GitHub. → **Expect:** the browser shows a "You're signed in — return to Solus" page; the app receives the callback, exchanges the code, and navigates on (onboarding for a new user, home for a returning one) within a second or two.
3. Cancel/close the browser tab without approving. → **Expect:** after the timeout (5 min) the button shows a "timed out" error; you can retry. (Retrying immediately while the first is still listening shows "a sign-in is already in progress".)

- [ ] 5.1 GitHub button opens the system browser to the authorize page
- [ ] 5.2 Approving signs you in and continues into the app
- [ ] 5.3 A new GitHub user lands in onboarding; a returning one lands on home
- [ ] 5.4 Browser preview (no Electron) shows the "desktop app only" message
- [ ] 5.5 Token only in request headers; the auth code is never logged

## Cross-cutting

- [ ] X.1 No CORS errors in the console (API allows the renderer origin + Authorization header)
- [ ] X.2 No secrets in logs or network responses (tokens only in request headers)
- [ ] X.3 `http://localhost:8000/api/v1/docs` lists users/teams/projects/jobs routes

## Known limitations (not bugs)

- Connecting tools and "building the graph" are still simulated — Sources (API §2.5) and Graph (§2.4) are later phases; the project's entity/relation counts are genuinely 0.
- `SOLUS_AUTO_CREATE_TABLES` is a dev convenience (no Alembic migrations yet). Do not enable it in a shared/prod database.
- GitHub OAuth uses a loopback localhost listener (port 53682) + the system browser; it works in the Electron app only, and needs the one-time GitHub/Supabase setup in Flow 5. The live round-trip could not be verified in the build environment (no browser/Supabase project).
