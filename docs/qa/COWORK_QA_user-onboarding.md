# COWORK QA — User Onboarding (SOLUSDEV-4)

End-to-end test plan for the Solus desktop auth doorway + first-run onboarding. Written to be run with only the application and this file.

## Scope

Frontend slice in `apps/desktop`: Landing → Signup/Login (Supabase or dev bypass) → Onboarding (About → Connect → Build) → Workspace home placeholder. **The connect and build steps are intentionally simulated** (animated, no live OAuth/sync/graph) — this is a visual prototype slice; do not expect real GitHub/KiCad/Onshape/ROS data.

## Setup

You can run this two ways:

- **Dev bypass (recommended for QA, no accounts needed):** leave `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` unset. Any email + 8+ char password "works"; GitHub button signs you in as a stub user. This exercises all flows without external services.
- **Real Supabase:** set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (see `apps/desktop/.env.example`) to a Supabase project with email + GitHub providers enabled.

Run the app:

1. `cd apps/desktop && pnpm install`
2. `pnpm dev` (launches Electron), **or** `pnpm build` then serve `out/renderer/` statically and open `index.html#/` in a browser (the screens run without Electron).

To reset to a clean first-run between cases: open devtools console and run `localStorage.clear()`, then reload. (Onboarding completion and the dev-bypass session are persisted in localStorage.)

Routes (hash): `#/` (smart root), `#/login`, `#/signup`, `#/onboarding`.

---

## Flow 1 — Landing page

1. Launch the app fresh (cleared storage). → **Expect:** Landing page. Top strip "SOLUS // CROSS-DOMAIN INTEGRITY FOR ROBOTICS TEAMS" + version. Hero "Your robot is one system. / Your tools aren't." (second line in accent color). Nav: Product / Docs / Pricing, "Sign in", "Get started". A domain-colored entity chain (`motor_driver.c → M3_PWM → DRV8316C·U4 → knee gearbox 9:1 → τ3 torque`) with colored dots. Footer "WORKS WITH GITHUB · KICAD · ONSHAPE · ROS 2".
2. Click "Get started" or "Create account". → **Expect:** navigates to Signup.
3. Go back; click "Sign in". → **Expect:** navigates to Login.

- [ ] 1.1 Landing renders with hero, chain, footer
- [ ] 1.2 "Get started"/"Create account" → Signup
- [ ] 1.3 "Sign in" → Login

## Flow 2 — Signup

1. From Landing, go to Signup. → **Expect:** "Create your workspace" card, "Continue with GitHub", an OR divider, WORK EMAIL + PASSWORD fields, "Create account", and a footer "Already have an account? Sign in".
2. Click "Create account" with both fields empty. → **Expect:** inline errors ("Enter a valid email address", "At least 8 characters"). No navigation.
3. Enter `not-an-email` + `short`, submit. → **Expect:** same two validation errors; fields outlined in the error color.
4. Enter a valid email and an 8+ char password, submit. → **Expect:** brief "Creating workspace…" spinner, then navigation to **Onboarding** (About step).
5. (Reset storage.) Return to Signup, click "Continue with GitHub". → **Expect (dev bypass):** "Authorizing with GitHub…" then onboarding. **(Real Supabase):** GitHub OAuth begins.
6. Footer "Sign in" link — click it, and also tab to it and press Enter. → **Expect:** both navigate to Login (keyboard works).

- [ ] 2.1 Signup renders all controls
- [ ] 2.2 Empty submit shows both field errors, no nav
- [ ] 2.3 Invalid email + short password show errors
- [ ] 2.4 Valid submit → Onboarding
- [ ] 2.5 GitHub button authorizes
- [ ] 2.6 Footer link works by click AND Enter key

## Flow 3 — Login

1. Navigate to Login. → **Expect:** "Welcome back" card, GitHub button, EMAIL + PASSWORD, "Sign in", an "Email me a magic link instead" button, footer "New to Solus? Create account".
2. Submit empty / invalid. → **Expect:** validation error shown under the password field.
3. Enter valid email + password, submit. → **Expect:** "Signing in…" then navigation to `#/` which resolves to onboarding (if not yet onboarded) or the workspace home (if already onboarded).
4. Enter a valid email, click "Email me a magic link instead". → **Expect (dev bypass):** treated as signed in. **(Real Supabase):** "Magic link sent — check your email." confirmation; no error.
5. With an empty/invalid email, click the magic-link button. → **Expect:** email validation error; no link sent.

- [ ] 3.1 Login renders all controls incl. magic-link
- [ ] 3.2 Invalid submit shows error
- [ ] 3.3 Valid sign-in routes correctly
- [ ] 3.4 Magic link confirmation / sign-in
- [ ] 3.5 Magic link blocked on invalid email

## Flow 4 — Onboarding: About step

1. Reach Onboarding after signup. → **Expect:** header with SOLUS wordmark, step dots (ABOUT active; CONNECT, BUILD dimmed), your email (uppercased) at right. Heading "What are you building?", a description textarea, two "STARTING POINT" cards (Connect / Template — "Connect my existing tools" selected by default with accent border), a "HOW SHOULD SOL TALK TO YOU?" Guide/Expert control, and a "Continue" button.
2. Type a description. → **Expect:** text accepted.
3. Toggle SOL mode to "Expert". → **Expect:** the helper text changes ("Terse, leads with the answer…"). (This persists as a user setting.)
4. With "Connect my existing tools" selected, click Continue. → **Expect:** advances to the Connect step.

- [ ] 4.1 About step renders with step dots + email
- [ ] 4.2 Description input works
- [ ] 4.3 SOL mode toggle changes helper text
- [ ] 4.4 Continue (connect path) → Connect step

## Flow 5 — Onboarding: Template path

1. On About, click "Start from a template robot". → **Expect:** a 4-card grid of templates appears (Quadruped / Diff-drive rover / Robot arm / Quadcopter). Continue becomes **disabled**.
2. Click Continue while no template is selected. → **Expect:** nothing happens (disabled).
3. Select a template (e.g. Quadruped). → **Expect:** card highlights; Continue enables.
4. Click Continue. → **Expect:** skips straight to the **Build** step (template pre-connects all sources), build log animates, completes.

- [ ] 5.1 Template grid appears
- [ ] 5.2 Continue disabled until a robot is picked
- [ ] 5.3 Selecting a template enables Continue
- [ ] 5.4 Continue → Build step (sources pre-connected)

## Flow 6 — Onboarding: Connect step

1. From About (connect path) → Connect. → **Expect:** heading "Connect your tools", four tiles (GitHub, KiCad, Onshape, ROS 2) each "Not connected", a counter "0 OF 4 CONNECTED (NEED 2+)", and a **disabled** "Build context model" button.
2. Click one tile (e.g. GitHub). → **Expect:** tile shows a spinner and cycles status lines ("Authorizing…", "Cloning…", "Indexing…"), border turns accent, then resolves to a green check + result text ("Connected — 2 repos, 214 files…").
3. Connect a second tile. → **Expect:** counter updates; at 2 connected it reads "2 OF 4 CONNECTED — READY" (green) and "Build context model" **enables**.
4. Click an already-connecting/connected tile. → **Expect:** no re-trigger (only idle tiles are clickable).
5. Click "Build context model". → **Expect:** advances to Build step.

- [ ] 6.1 Connect step renders 4 tiles + disabled Build button
- [ ] 6.2 Connecting a tile animates → connected (green)
- [ ] 6.3 Counter updates; Build enables at 2+
- [ ] 6.4 Connected/busy tiles aren't re-triggered
- [ ] 6.5 Build button advances to Build step

## Flow 7 — Onboarding: Build step + handoff

1. Enter Build. → **Expect:** heading "Building your context model", a "working…" spinner, and log lines appearing one by one with green checks and right-aligned stats (parsing schematic, indexing firmware, reading assemblies, mapping ROS graph, resolving links, checking contracts).
2. Wait for completion (a few seconds). → **Expect:** heading changes to "Context model ready", subtext "247 nodes · 31 cross-domain links · 2 issues already flagged", and an "Open workspace" button appears.
3. Click "Open workspace". → **Expect:** navigates to the workspace home: "Your context model is ready", a welcome line with your email, "SOL · GUIDE/EXPERT" reflecting your chosen mode, and a "Sign out" button.

- [ ] 7.1 Build log animates line-by-line
- [ ] 7.2 Completes to "Context model ready" + Open workspace
- [ ] 7.3 Open workspace → workspace home (shows email + SOL mode)

## Flow 8 — Guards, persistence & edge cases

1. After completing onboarding, manually navigate to `#/onboarding`. → **Expect:** redirected to `#/` (workspace home) — you cannot re-run onboarding once complete.
2. While signed in, navigate to `#/login` or `#/signup`. → **Expect:** redirected to `#/` (workspace home).
3. While signed out (clear storage, reload), navigate to `#/onboarding`. → **Expect:** redirected to `#/login`.
4. Reload the app after completing onboarding (without clearing storage). → **Expect:** lands on the workspace home (session + onboarded state persisted).
5. Click "Sign out" on the workspace home. → **Expect:** returns to Landing; navigating to `#/onboarding` now redirects to login.
6. Switch SOL mode in onboarding to Expert, finish, reach home. → **Expect:** home shows "SOL · EXPERT".

- [ ] 8.1 Completed users can't re-enter /onboarding
- [ ] 8.2 Signed-in users redirected off /login and /signup
- [ ] 8.3 Signed-out users redirected off /onboarding → login
- [ ] 8.4 Session + onboarded persist across reload
- [ ] 8.5 Sign out returns to Landing and clears access
- [ ] 8.6 Chosen SOL mode reflected on the workspace home

## Cross-cutting checks

- [ ] X.1 No console errors during any flow
- [ ] X.2 Fonts render as IBM Plex (Sans for UI, Mono for labels/logs) — not a system fallback
- [ ] X.3 Dark theme + amber accent applied consistently; domain colors (sw=blue, ee=amber, me=pink, rt=green) correct on the Landing chain
- [ ] X.4 Keyboard: Enter submits forms; footer auth links reachable by Tab + Enter
- [ ] X.5 (Real Supabase only) Sign-in errors from Supabase surface as readable messages, not crashes

## Known limitations (not bugs)

- Connect/build are simulated — no real source connection, sync, or graph is created.
- GitHub OAuth in dev bypass is a stub; full Electron OAuth deep-link handling is not implemented in this slice.
- The workspace home is a placeholder; the real workspace (graph/bench/agent) is a separate feature area.
