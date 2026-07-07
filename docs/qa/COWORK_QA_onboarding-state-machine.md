# COWORK QA — Onboarding Pipeline & State Machine (SOLUSDEV-88)

End-to-end test plan for the first-run pipeline: landing→signup handoff, the
guided welcome→team→project flow, server-persisted resume, and the guarantee
that **connections never block reaching the workspace**.

## Required setup state

- [ ] API + desktop app running; Supabase auth configured (real signup possible).
- [ ] A fresh email address (or delete the test account first) for the
      first-run path.
- [ ] Optional for the connect path: GitHub OAuth env per
      `docs/integrations/github-setup.md`.

## Flow 1 — Fresh signup straight to workspace with NO connections

1. From the landing page, sign up with a fresh account. **Expected:** after the
   session exists you land in first-run onboarding (About step), not the
   workspace.
2. Describe the robot, keep "connect your tools", Continue. **Expected:**
   Connect step; a team+project are provisioned in the background.
3. Connect **nothing**. **Expected:** the primary "Build context model" button
   is disabled but a **"Skip for now"** button is present and enabled, with copy
   noting tools can be connected later.
4. Click Skip for now. **Expected:** Build step runs and completes; "Open
   workspace" appears.
5. Open workspace. **Expected:** the workspace home (dashboard). The project
   from step 2 exists (`GET /teams/{tid}/projects`).
6. Sign out and sign back in. **Expected:** you land **directly on the
   homepage** — onboarding does not reappear (server-side `onboarding_step` is
   `done`).

## Flow 2 — Resume mid-flow

7. With a second fresh account, advance to the Connect step, then quit/reload
   the app. **Expected:** after reload you are back on the **Connect** step
   (not About) — the step came from the server (`GET /users/me/settings` →
   `onboarding_step: "connect"`).
8. Advance to Build, reload before clicking Open workspace. **Expected:**
   resumes at Build.
9. Log in as this mid-flow account on a different machine (or after clearing
   local storage). **Expected:** resumes at the saved step there too.

## Flow 3 — Template path

10. Fresh account → About step → "Start from a template robot" → pick one →
    Continue. **Expected:** jumps straight to Build (sources pre-simulated),
    completes to the workspace as in Flow 1.

## Flow 4 — Connections optional but available

11. Fresh account → Connect step → connect GitHub for real (or two simulated
    tiles). **Expected:** with 2+ connected the primary button enables and
    "Skip for now" disappears; Build proceeds identically.

## Edge cases & failure paths

- [ ] **API down / dev bypass:** stop the API mid-onboarding. **Expected:** the
      flow still completes locally (no hang, no crash); step persistence resumes
      on the next successful call.
- [ ] Unauthenticated visit to `/onboarding`. **Expected:** redirected to login.
- [ ] Already-onboarded user visits `/onboarding` directly. **Expected:**
      redirected to the homepage.
- [ ] `PATCH /users/me/settings {"onboarding_step": "bogus"}`. **Expected:** 422.
- [ ] Brief splash while the saved step loads is acceptable; a hang is not.

## Sign-off

- [ ] Flow 1 passes — **zero connections, straight to homepage** — and survives
      re-login (step 6).
- [ ] Flows 2–4 pass; edge cases behave as described.
