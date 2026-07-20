# COWORK QA — SOLUSDEV-152: Remove test data & make Solus production-usable

Self-sufficient test plan for Claude Cowork. You need: the running application (setup
below) and this file. No implementation context required.

**What this ticket did:** removed ALL fabricated demo data from the desktop app (the
"strider-qd12" fake robot, scripted SOL replies, fake telemetry, fake alerts), replaced
it with honest empty states and real API-backed reads; made the onboarding build step
show real sync progress; made production builds fail without real auth config; fixed
the API deploy config so containers boot on a fresh database; completed the env
template. **The core assertion behind every check: the app must never present
fabricated content as real.** If you ever see a robot named "strider-qd12", a teammate
named "Priya", a "247 NODES" stat, telemetry labeled "REAL · STREAMING", or a fake
"Opening PR #144" animation — that is a FAIL.

---

## Required setup

1. Postgres + Redis running (`docker compose -f docker-compose.dev.yml up -d`).
2. `cp env.mega.example .env.mega`, fill: `SOLUS_SUPABASE_JWT_SECRET`,
   `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (a real Supabase project),
   `SOLUS_REDIS_URL=redis://localhost:6379`; for GitHub flows also
   `SOLUS_GITHUB_CLIENT_ID`/`_SECRET` (a GitHub OAuth app). Run `pnpm env:sync`.
3. API: `cd packages/api && uv run alembic upgrade head && uv run uvicorn --factory solus_api.main:create_app --port 8000`.
4. Worker (only for scheduled/background flows): `cd packages/api && uv run arq solus_api.worker_main.WorkerSettings`.
5. Desktop: `pnpm --filter @solus/desktop dev` (or a packaged build for §7).
6. Two Supabase test accounts (fresh emails) — one main, one for team flows.
7. A KiCad netlist export file (.net/.xml) for the EDA connect flow.

---

## 1. Fresh account onboarding (happy path)

- [ ] 1.1 Sign up with a fresh email → email verification → sign in. Expect real
      Supabase flow; no "dev@solus.local" ever appears.
- [ ] 1.2 About/plan step: there is NO "template robot" / starting-point picker.
      Continue always leads to the Connect step.
- [ ] 1.3 Connect step shows ONLY connectable providers: GitHub, GitLab, KiCad,
      Altium. Onshape and ROS 2 tiles must NOT exist anywhere.
- [ ] 1.4 KiCad tile copy mentions committed netlist export — NOT "Watching project
      folder…" (the backend does not watch folders).
- [ ] 1.5 Connect GitHub (OAuth) → real repo authorization → tile shows real result
      (repo count), not "Connected — 2 repos, 214 files, 31k LOC indexed".
- [ ] 1.6 Connect KiCad via file-pick with your netlist export → tile reflects the
      real parse result.
- [ ] 1.7 Build step: shows per-source sync lines with REAL states (pending/ok/failed)
      that change as syncs actually complete — not a scripted log animation. Final
      stat is a real entity count (small number for a small netlist), never
      "GROUNDED IN 247 NODES · 31 CROSS-DOMAIN LINKS".
- [ ] 1.8 Edge: stop the API mid-connect → tile shows an honest retryable error
      ("Solus API unreachable…"), not a fake success.
- [ ] 1.9 Edge: skip connecting entirely → you still reach the workspace (skip is a
      supported path), with empty states everywhere (§2).

## 2. Workspace screens — fresh account, zero sources

Every screen must render an honest empty state. NO fabricated robot data anywhere.

- [ ] 2.1 Home: your real team/projects (or none); no "strider-qd12 · Six-wheel
      autonomous rover" card.
- [ ] 2.2 Topbar: real project name if one exists, else "No project" — never
      "strider-qd12".
- [ ] 2.3 Graph: layout shell renders with "Connect a source to start building your
      robot's graph"; footer has NO fake counts.
- [ ] 2.4 Alerts: no alerts exist; NO toast "Priya swapped U4…" ever fires; no
      pre-seeded alert list.
- [ ] 2.5 Bench: "Live Bench isn't streaming yet" + NO DEVICE CONNECTED; there is NO
      fake device ("STRIDER-QD12 #A3 · USB-C · fw 0.9.2") and NOTHING labeled
      "REAL · STREAMING · 500 HZ".
- [ ] 2.6 SOL: orb renders, status NOT CONNECTED, no chat input that fake-replies;
      Guide/Expert toggle works and persists (it's a real setting).
- [ ] 2.7 Team: your real solo roster; no fake members/activity.

## 3. Workspace screens — after a real sync (GitHub or KiCad connected)

- [ ] 3.1 Graph: footer shows real `N ENTITIES · M RELATIONS · K SOURCE(S)` matching
      the sync (verify N > 0 and plausible for your repo/netlist).
- [ ] 3.2 Graph empty-state progression: with a source but before first sync
      completes → "Waiting for your first sync"; after entities exist → "Your graph
      is taking shape".
- [ ] 3.3 Home/Team reflect real data; counts consistent with what you connected.

## 4. Settings (interacts with SOLUSDEV-82/86 — regression surface)

- [ ] 4.1 Profile: display-name edit saves; email read-only.
- [ ] 4.2 Integrations section lists only real connectors (matches §1.3 roster).
- [ ] 4.3 Account danger zone: delete flow — first click reveals confirm, cancel
      backs out, confirm deletes, signs out, and a subsequent sign-in with the same
      (now-deleted) session token does NOT resurrect the account.
- [ ] 4.4 Sole-owner block: as the sole owner of a shared team with another member,
      delete is refused with the transfer-ownership message (409 path).
- [ ] 4.5 Password reset (SOLUSDEV-82): request reset → email OTP → new password
      works. Must still work post-152.

## 5. API/deploy behavior (ops-facing)

- [ ] 5.1 `docker build -f infrastructure/docker/api.Dockerfile .` succeeds; running
      it against a FRESH empty Postgres applies migrations then serves (no
      `solus_api.main:app` crash, no missing-tables errors).
- [ ] 5.2 `/readyz` with `SOLUS_REDIS_URL` unset/empty: `"redis": "not_configured"`,
      `"queue": "not_configured"`, overall status still ok (degraded mode is
      accepted and documented in infrastructure/aws/README.md).
- [ ] 5.3 `/readyz` with Redis configured: both report `configured`.
- [ ] 5.4 Unreachable database → `/readyz` returns 503.
- [ ] 5.5 Job cancel: POST cancel on a running job marks it CANCELLED but does not
      abort in-flight work (documented semantics — verify docstring matches
      behavior, not that it aborts).

## 6. Env template (operator onboarding)

- [ ] 6.1 Fresh `cp env.mega.example .env.mega` → fill only the keys marked required
      → `pnpm env:sync` → API boots and desktop dev server runs. No key the code
      needs is missing from the template.
- [ ] 6.2 `VITE_API_BASE_URL` in the synced desktop env ends with `/api/v1`.
- [ ] 6.3 Template contains NO real secrets (placeholders only) and documents that
      AI provider keys are SecretStore secrets, not env vars.

## 7. Production build guard (release-engineering flow)

- [ ] 7.1 With `apps/desktop/.env` absent/moved aside: `pnpm --filter @solus/desktop
    build` FAILS with `[solus-prod-auth-guard] Refusing to build…` naming both
      VITE*SUPABASE*\* vars.
- [ ] 7.2 With real (or dummy) VITE*SUPABASE*\* present: build succeeds.
- [ ] 7.3 Grep the built bundle: `grep -c 'dev-bypass-token\|dev@solus.local\|strider-qd12'
    apps/desktop/out/renderer/assets/*.js` → 0 hits.
- [ ] 7.4 Dev server (`pnpm --filter @solus/desktop dev`) WITHOUT Supabase env still
      works with the dev bypass (local development is preserved) — but any BUILT
      output never contains the bypass.

## 8. Cross-feature interactions

- [ ] 8.1 Team invite → second account joins → roster updates (Teams feature intact).
- [ ] 8.2 Subscription plan visible/patchable in settings (billing surface intact).
- [ ] 8.3 Unverified email: sensitive actions (create team, invite, connect source,
      delete account) are refused with the verify-email message until verified.
- [ ] 8.4 Sync failure path: connect a KiCad file that is NOT a valid netlist →
      source shows a real error state; Build step shows the real failure, no fake
      success.

## Known-good exclusions (do NOT file as failures)

- SOL does not answer messages (chat wiring + real model calls are SOLUSDEV-132/134 +
  MO-01 — the screen says so honestly).
- Graph has no interactive node canvas yet (SOLUSDEV-109/110/112).
- Alerts stay empty until checkers surface warnings in-app (SOLUSDEV-117/118).
- Bench streams nothing until Live Bench device I/O lands (SOLUSDEV-121–126).
- Onshape/ROS cannot be connected (correctly absent from the UI).
- Scheduled auto-resync and credit-debit reconciliation require the ARQ worker (§Setup 4).
