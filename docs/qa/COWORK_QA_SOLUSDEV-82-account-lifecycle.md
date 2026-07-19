# COWORK QA — Account-lifecycle edges (SOLUSDEV-82 / SOLUS-FND-02)

End-to-end test plan for the account-lifecycle edges: **password reset**,
**email-verification gating**, and **account deletion** (owned-team transfer/
block, credit forfeiture, session revocation, remaining-member notification).
Written to be run against a running app with only this file.

## Required setup state

- [ ] API running (`make dev-api`) with a Postgres DB (`make db-up`), migrated
      to head (`alembic upgrade head`). Desktop app running (`pnpm dev:desktop`).
- [ ] **Supabase auth configured** (`VITE_SUPABASE_*`, `SOLUS_SUPABASE_JWT_SECRET`).
      Without it the app runs the offline demo and the live flows below do NOT
      engage.
- [ ] For durable deletion + session revocation to fully work, set
      `SOLUS_SUPABASE_URL` and `SOLUS_SUPABASE_SERVICE_ROLE_KEY` on the API.
      When unset, deletion still removes all local data and tombstones the
      identity, but the Supabase auth user/session is not remotely revoked (a
      warning is logged) — note this in results if you tested without the key.
- [ ] Two real accounts you can sign in as: **User A** and **User B**
      (different emails). For email-verification tests you need at least one
      account whose email is **not yet confirmed** in Supabase.

Checklist legend: ✅ pass · ❌ fail · ➖ blocked/NA

---

## Flow 1 — Password reset (in-app recovery, NEW)

1. Sign out. On the **Sign in** screen, click **Forgot password?**.
   - [ ] Routes to a "Reset your password" screen with an EMAIL field.
2. Enter User A's email, click **Send recovery code**.
   - [ ] Success; the screen advances to a RECOVERY CODE + NEW PASSWORD step.
   - [ ] A recovery email arrives from Supabase with a code.
3. Enter the emailed code and a new password, click **Set new password**.
   - [ ] "Password updated" confirmation shows.
4. Click **Back to sign in** and sign in with the **new** password.
   - [ ] Sign-in succeeds.
5. Failure paths:
   - [ ] A malformed email on step 1 → inline error, stays on step 1.
   - [ ] A wrong/expired code on step 2 → inline error, no password change.

---

## Flow 2 — Email-verification gating (NEW)

Use an account whose email is **not confirmed** in Supabase (User B fresh signup
before clicking the confirmation link, if your Supabase project allows a session
pre-confirmation; otherwise verify the backend behavior via API in step 4).

1. Signed in as an **unverified** user, land in the workspace.
   - [ ] A banner reads "Verify your email to create teams, invite members, and
         connect sources," with a **Resend email** button.
2. Click **Resend email**.
   - [ ] Shows "Verification email sent."; a new confirmation email arrives.
3. Try a gated action while unverified — e.g. Home → **New team**.
   - [ ] The action is rejected (server returns 403 `email_not_verified`); the
         UI does not create the team.
4. API-level confirmation (if you have a bearer token for an unverified user, or
   can mint one with `email_verified:false`): `POST /api/v1/teams`,
   `POST /api/v1/teams/{id}/invites`, `POST /api/v1/projects/{id}/sources`,
   `DELETE /api/v1/users/me` all return **403 `email_not_verified`**.
   - [ ] All four gated; **GET** endpoints and settings still work.
5. Confirm the email (click the Supabase link), refresh/sign in again.
   - [ ] Banner is gone; the gated actions now succeed.

> Note: a token that carries **no** `email_verified` claim at all is treated as
> verified (documented default) — gating engages only on an explicit `false`.

---

## Flow 3 — Account deletion: happy path (NEW)

Sign in as a user who is **not** the sole owner of any shared team (e.g. a fresh
account with only its personal team, or a member of someone else's team).

1. Go to **Settings** → scroll to the **Account** section → **Delete account**.
   - [ ] A confirmation appears ("This permanently deletes your account…") with
         **Cancel** / **Delete account**. Nothing deleted on the first click.
2. Click **Cancel** → nothing happens. Reopen and click **Delete account**.
   - [ ] The account is deleted; the app returns to the landing/sign-in screen
         (session torn down).
3. Try to sign back in / reuse the old session.
   - [ ] With the service-role key configured: the Supabase user is gone; you
         cannot sign in with the old credentials.
   - [ ] Even without it: an API call with the old token returns **401
         `account_deleted`** (durable — no zombie re-provision).

---

## Flow 4 — Account deletion: sole-owner block + transfer (NEW)

1. As User A, create a team ("QA Robotics") and invite User B; User B accepts so
   the team has two members with A as the only owner.
2. As User A, **Settings → Account → Delete account → confirm**.
   - [ ] Deletion is **blocked**; an inline message says you solely own a shared
         team and must transfer ownership first (409 `ownership_transfer_required`).
   - [ ] The account is NOT deleted; you stay signed in.
3. As User A, go to **Team**, change User B's role to **owner** (transfer).
4. Retry **Settings → Account → Delete account → confirm**.
   - [ ] Deletion now succeeds.
   - [ ] As User B: the team still exists; User B receives a **"A left QA
         Robotics"** notification (member.left), and A is no longer a member.

---

## Flow 5 — Credit forfeiture & ledger preservation (data integrity)

Requires DB access (or engineering) to verify the ledger.

1. Seed a `credit_balance` (e.g. 500) and a `credit_ledger` row for a test user.
2. Delete that user's account (Flow 3).
   - [ ] The `credit_balance` row is gone.
   - [ ] The original `credit_ledger` row **still exists** with `user_id` NULL
         (anonymized, not deleted — ADR-024).
   - [ ] A new `credit_ledger` ADJUSTMENT row exists: `amount = -500`,
         `balance_after = 0`, `attrs.reason = "account_deleted"`.

---

## Cross-tenant isolation (must pass)

- [ ] User B (non-member) cannot delete User A or affect A's teams via any
      endpoint.
- [ ] Deleting User A does not delete shared teams A belonged to; only A's own
      membership is removed and A's solo teams are cascaded.
- [ ] Another user's notifications never contain A's account events except the
      intended `member.left` to co-members of teams A left.

## Edge cases & failure paths

- [ ] Delete-account while unverified → 403 (gated), not deletion.
- [ ] Delete-account with no credits → succeeds; no forfeiture row written.
- [ ] Password reset with an email that has no account → Supabase returns
      success without leaking existence (no account enumeration); no code works.
- [ ] Resend verification repeatedly → rate-limited by the global limiter
      (429 after the window cap); no crash.

## Sign-off

- [ ] Flows 1–5 pass.
- [ ] All isolation checks hold.
- [ ] Deletion is durable and, with the service-role key set, revokes the
      Supabase session.

## Known scope notes (this cycle)

- Password-reset email + email-verification email delivery are **Supabase-side**
  (ADR-009); the backend has no reset/verify routes by design.
- Without `SOLUS_SUPABASE_SERVICE_ROLE_KEY`, remote session revocation is a
  logged no-op; local deletion + the tombstone still make deletion durable
  against re-provision.
