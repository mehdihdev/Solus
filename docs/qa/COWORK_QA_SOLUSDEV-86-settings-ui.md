# Cowork QA — SOLUSDEV-86 (SOLUS-FND-06) Settings UI surfaces

End-to-end test plan for the desktop **Settings** screen. Written to be self-sufficient: you
need the running desktop app and this file, nothing else.

---

## What this feature is

The Settings screen (gear icon in the left rail) is the user's control surface for their profile,
preferences (SOL answer mode + appearance), privacy (data-collection consent), billing summary,
connected integrations, and — for a team — member management and team settings. Forms persist to
the Solus backend and show inline errors from the API error envelope. Appearance is a local-only
preference; everything else round-trips to the API when the workspace is connected ("online").

## Required setup state

1. **Backend running** and the desktop app pointed at it (`VITE_API_BASE_URL`, default
   `http://localhost:8000/api/v1`). Bring up the API per `docs/api/API-implementation.md` §1.
2. **A signed-in user** (Supabase JWT / dev bypass). First authenticated request auto-provisions
   the user + personal team + a trialing subscription.
3. **A non-personal team** where the signed-in user is **owner**, with at least one other member
   and optionally one pending invite — needed for the Members and Team sections. (Create a team,
   invite a second user, accept as that user.)
4. To exercise the **offline** path: run the renderer without a reachable API (dev bypass) so the
   workspace is not "linked".

Reach the screen: click the **gear (Settings)** button at the bottom of the left rail.

---

## Flow 1 — Screen loads and renders all sections (online, team owner)

| #   | Step                           | Expected                                                                                                           |
| --- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| 1   | Open Settings                  | Brief spinner, then the screen with heading **"Settings"**                                                         |
| 2   | Observe sections top-to-bottom | **Profile**, **SOL**, **Appearance**, **Privacy**, **Billing**, **Integrations**, **Members**, **Team** all render |
| 3   | No fabricated data             | Billing shows your real plan/trial/seats/limits (not a hardcoded "1840/5000" meter)                                |

- [ ] Pass - [ ] Fail

## Flow 2 — Profile: edit display name

| #   | Step                                                     | Expected                                                          |
| --- | -------------------------------------------------------- | ----------------------------------------------------------------- |
| 1   | In **Profile**, clear the name field and type a new name | Field updates; avatar initials/name preview track what you type   |
| 2   | Click **Save**                                           | Button shows "Saving…" then returns; name persists                |
| 3   | Navigate away (e.g. Home) and back to Settings           | New name still shown (persisted server-side)                      |
| 4   | Edge: clear the field to blank and Save                  | Inline error "Name cannot be blank."; no API call; name unchanged |

- [ ] Pass - [ ] Fail

## Flow 3 — SOL answer mode (backend-persisted, ADR-016)

| #   | Step                                                        | Expected                                                |
| --- | ----------------------------------------------------------- | ------------------------------------------------------- |
| 1   | In **SOL**, switch **Answer mode** from Guide to **Expert** | Toggle flips immediately (optimistic)                   |
| 2   | Reload the app / re-open Settings                           | Mode is still **Expert** (persisted)                    |
| 3   | Confirm app-wide effect                                     | Other SOL natural-language surfaces reflect Expert mode |

- [ ] Pass - [ ] Fail

## Flow 4 — Appearance (local-only)

| #   | Step                               | Expected                                               |
| --- | ---------------------------------- | ------------------------------------------------------ |
| 1   | Change **Theme** in the dropdown   | UI re-skins immediately                                |
| 2   | Click an **Accent** swatch         | Accent applies; selected swatch is ringed              |
| 3   | Toggle **Density** compact/regular | Layout density changes                                 |
| 4   | Restart the app                    | Appearance choices persist locally (no network needed) |

- [ ] Pass - [ ] Fail

## Flow 5 — Privacy: data-collection consent (ADR-011)

| #   | Step                                                         | Expected                    |
| --- | ------------------------------------------------------------ | --------------------------- |
| 1   | In **Privacy**, set **Data collection** to **Off**           | Toggle flips optimistically |
| 2   | Re-open Settings                                             | Still **Off** (persisted)   |
| 3   | Set back to **On**                                           | Persists as On              |
| 4   | The copy states designs/code/credentials are never collected | Present and accurate        |

- [ ] Pass - [ ] Fail

## Flow 6 — Billing summary (read-only, live subscription)

| #   | Step                         | Expected                                                                       |
| --- | ---------------------------- | ------------------------------------------------------------------------------ |
| 1   | Read the **Billing** section | Shows **Plan** (e.g. Basic) + status badge (e.g. TRIAL)                        |
| 2   | If trialing                  | A **Trial ends** row shows "in N days" (or "today")                            |
| 3   | **Seats** row                | Shows the seat count                                                           |
| 4   | Plan limits                  | Integrations / Projects / Teams rows show numbers, or **Unlimited** for no cap |
| 5   | Security check               | No Stripe IDs, customer IDs, or any secret/credential is displayed anywhere    |

- [ ] Pass - [ ] Fail

## Flow 7 — Integrations overview

| #   | Step                  | Expected                                                             |
| --- | --------------------- | -------------------------------------------------------------------- |
| 1   | Read **Integrations** | Every connector (GitHub, KiCad, Onshape, …) listed with its monogram |
| 2   | A connected source    | Shows green **● CONNECTED**                                          |
| 3   | Unconnected sources   | Show **○ NOT CONNECTED**                                             |

- [ ] Pass - [ ] Fail

## Flow 8 — Members management (roles from FND-01)

Preconditions: you are **owner/admin** of a non-personal team with ≥1 other member.

| #   | Step                                                              | Expected                                                                          |
| --- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| 1   | Read **Members**                                                  | Roster with each member's name/email + role; count line "N members (· M pending)" |
| 2   | Owner row                                                         | No role dropdown / remove control for the owner                                   |
| 3   | Change a member's role via the dropdown                           | Role updates (persists on refresh)                                                |
| 4   | Click **Invite teammate** → enter a valid email → **Send invite** | One-time join token shown once; done                                              |
| 5   | Invalid email in invite                                           | Inline "Enter a valid email address."; no send                                    |
| 6   | Revoke a pending invite (× button)                                | Invite disappears                                                                 |
| 7   | Remove a member (× button)                                        | Member disappears                                                                 |
| 8   | As a **viewer/member** (not manager)                              | No invite button, no role/remove controls; roster read-only                       |

- [ ] Pass - [ ] Fail

## Flow 9 — Team settings (owner)

| #   | Step                                               | Expected                               |
| --- | -------------------------------------------------- | -------------------------------------- |
| 1   | In **Team**, edit **Name** and click **Save**      | Team renamed (reflected across app)    |
| 2   | Toggle **Notify team on new projects** On/Off      | Persists                               |
| 3   | **Danger zone → Delete team** → **Confirm delete** | Team deleted after explicit confirm    |
| 4   | Cancel path: Delete team → **Cancel**              | No deletion                            |
| 5   | As **member/viewer**                               | Team name is read-only; no danger zone |
| 6   | **Personal workspace**                             | No Delete-team danger zone shown       |

- [ ] Pass - [ ] Fail

## Flow 10 — Offline / dev-bypass degradation

Precondition: run the renderer with no reachable API (workspace not linked).

| #   | Step                   | Expected                                                                |
| --- | ---------------------- | ----------------------------------------------------------------------- |
| 1   | Open Settings          | **Appearance** and **Integrations** still render and work               |
| 2   | SOL answer mode toggle | Still switches (kept as a local preference offline)                     |
| 3   | Account sections       | **Profile**, **Privacy**, **Billing**, **Members**, **Team** are hidden |
| 4   | A notice appears       | "Sign in to Solus to manage your profile, privacy, billing, and team…"  |

- [ ] Pass - [ ] Fail

## Flow 11 — Error envelope surfacing

Precondition: force a failure (e.g. act as a non-authorized user, or induce a 4xx/5xx on a save).

| #   | Step                                 | Expected                                                                |
| --- | ------------------------------------ | ----------------------------------------------------------------------- |
| 1   | Trigger a failing name save          | Inline error from the API message appears under the form; no crash      |
| 2   | Trigger a failing consent/SOL change | Toggle **reverts** to prior state; inline error shown                   |
| 3   | Verify                               | No stack traces, no secrets, no raw server internals leaked to the user |

- [ ] Pass - [ ] Fail

---

## Cross-feature interactions to verify

- [ ] Renaming the team in Settings updates the Team screen and shell chrome.
- [ ] Member/role/invite changes made in Settings match what the **Team** screen shows (both use the
      same shared members component and data hook).
- [ ] SOL mode changed in Settings is respected by the SOL agent and other NL surfaces (ADR-016).
- [ ] Switching the active team (multi-team users) re-scopes Members/Team sections correctly.

## Regression checks

- [ ] The **Team** screen still renders roster, activity, invite flow, and role/remove controls
      exactly as before the member-UI was extracted into the shared component.
- [ ] No console errors in the renderer devtools while using Settings.
