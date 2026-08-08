# Cowork QA — Stripe Billing & Checkout (SOLUSDEV-83 follow-up)

End-to-end test plan for the "select a plan → pay through Stripe" feature. Written
to be run against a running Solus app with this file and nothing else.

## What this feature adds

- **Backend** — `POST /api/v1/billing/checkout-session` (subscription or credit
  pack), `POST /api/v1/billing/portal-session` (Stripe billing portal), `GET
/api/v1/billing/packs`, `GET /api/v1/users/me/credits`; the webhook now sets the
  local plan/limits from the purchased Stripe Price.
- **Desktop** — the Billing screen "Subscribe" buttons open real Stripe Checkout in
  the browser (monthly/yearly toggle), a "Manage billing" button opens the Stripe
  portal, a "Buy credits" section purchases packs, and the current-plan card shows
  the live credit balance. On return from the browser the screen refetches.

## Required setup state

1. **Postgres + API + desktop running** (`pnpm dev:all`), signed in as a real
   Supabase user (so a subscription is auto-provisioned; trial credits granted).
2. **Stripe test-mode configured** (this is the operator step that makes it
   transact live). Use the operator CLI from `packages/api`:

   - `uv run stripe-setup put-key` — stores a Stripe **test** secret key
     (`sk_test_...`) in the SecretStore (interactive prompt).
   - `uv run stripe-setup bootstrap` — creates the ADR-023/024 plan/pack Prices
     in Stripe (idempotent) and prints the two `SOLUS_STRIPE_*` lines to paste.
   - `uv run stripe-setup check` — verifies the key and every configured price
     id; must print `check: PASS` before running the flows below.

   In `.env.mega` (then `pnpm env:sync`):

   - `SOLUS_STRIPE_WEBHOOK_SECRET` — optional in dev: `pnpm dev:all` derives it from
     the Stripe CLI automatically. In production it is the endpoint secret printed
     by `uv run stripe-setup webhook --url https://<api-host>` (or the dashboard).
   - `SOLUS_STRIPE_PLAN_PRICES` = JSON mapping `basic:month`/`basic:year`/`pro:month`/
     `pro:year` to test Price ids created in Stripe.
   - `SOLUS_STRIPE_PACK_CREDITS` = JSON mapping each pack's test Price id → credits.
   - `SOLUS_STRIPE_TRIAL_DAYS` (default 14) as desired.

3. **Forward webhooks** to the API: `pnpm dev:all` does this automatically when the
   Stripe CLI is installed and logged in (it derives the signing secret from the CLI
   and starts `stripe listen`); standalone: `pnpm dev:stripe`. **Without this
   forwarder a completed checkout never updates the local plan/credits.**
4. Stripe test card for checkout: `4242 4242 4242 4242`, any future expiry/CVC/zip.

> If Stripe is NOT configured yet, the feature must **degrade gracefully** (see the
> "Unconfigured" path) rather than crash — that path is testable without any Stripe
> account.

## Flow 1 — Subscribe to a plan (monthly)

1. Open the **Billing** screen from the left rail. → Current plan card + a "Plans"
   row with a Monthly/Yearly toggle and BASIC/PRO/Enterprise cards; credit balance
   shows on the current-plan card.
2. Ensure the toggle reads **Monthly**. Click **Subscribe · Monthly** on the PRO card.
   → A **"Secure checkout — Stripe" window opens inside the app** (SOLUSDEV-114) —
   no browser tab. The Billing buttons stay disabled while it is open.
3. Pay with the test card and complete checkout.
4. **Expected:** the checkout window **closes itself**; a notice appears
   ("Payment received — your plan and credits are updating now."); within a few
   seconds the current plan shows **Pro**, status **Active** (or Trialing), PRO
   limits (unlimited), and the **shell bell shows a "Payment successful /
   You're on the Pro plan" notification** without reloading. ✅ / ❌
5. **Cancel path:** start another checkout and close the window (or click Stripe's
   back/cancel link). → Notice "Checkout canceled — you haven't been charged.";
   plan unchanged; **no** payment notification in the bell. ✅ / ❌

## Flow 2 — Subscribe (yearly interval)

1. On Billing, click **Yearly** in the toggle. The PRO/BASIC buttons read
   **Subscribe · Yearly**.
2. Click **Subscribe · Yearly** on a non-current plan. → Checkout opens for that
   plan's **yearly** price. Complete it. → Plan updates as in Flow 1. ✅ / ❌

## Flow 3 — Buy a credit pack

1. On Billing, find the **Buy credits** section (shown when packs are configured).
   Each card shows a credit amount + **Buy**.
2. Click **Buy** on a pack. → The in-app checkout window opens for a one-time
   payment. Pay with the test card.
3. **Expected:** the window closes itself; the credit balance on the current-plan
   card increases by the pack's credits (after the webhook processes the paid
   session), and the bell shows a **"Credits added — N credits were added to your
   balance"** notification. ✅ / ❌

## Flow 4 — Manage billing (portal)

1. After at least one subscription checkout (so a Stripe customer exists), click
   **Manage billing** on the current-plan card. → The Stripe billing portal opens in
   the browser (update card, cancel, switch plan). ✅ / ❌
2. In the portal, cancel the subscription. Return to the app; after the webhook, the
   status reflects the change (Canceled / Past due as applicable). ✅ / ❌

## Flow 5 — Enterprise = contact sales

1. The Enterprise card shows **CONTACT SALES** (a mailto link), never a Subscribe
   button. Clicking it opens the mail client; no checkout is attempted. ✅ / ❌

## Edge cases & failure paths

- **Unconfigured (no Stripe key/prices):** click Subscribe. → No browser opens; a
  notice appears: "Billing isn't configured yet — add your Stripe keys and prices…".
  App does not crash. (Backend returns `503 billing_unconfigured`.) ✅ / ❌
- **Portal before any purchase:** on a brand-new account, "Manage billing" → notice
  "Start a subscription first to open the billing portal." (Backend `409`.) ✅ / ❌
- **Enterprise via API:** `POST /billing/checkout-session {kind:subscription,
plan:enterprise,interval:month}` → `400 plan_not_checkoutable`. ✅ / ❌
- **Unknown pack:** `{kind:pack, price_id:"price_bogus"}` → `400 invalid_pack`. ✅ / ❌
- **Auth required:** call any `/billing/*` route or `/users/me/credits` with no
  bearer token → `401`. ✅ / ❌
- **Entitlement follows payment, not the client:** you cannot obtain PRO/credits by
  calling the API directly — the plan/credits only change after Stripe's signed
  webhook confirms the purchased Price. Attempting to spoof is rejected at the
  webhook (bad signature → `400`). ✅ / ❌
- **Offline:** with the API unreachable, Billing shows the honest offline notice, not
  a broken screen. ✅ / ❌
- **Idempotency:** replay the same Stripe event (`stripe events resend <id>`) → no
  double credit grant, no duplicate state change. ✅ / ❌

## Cross-feature checks

- The credit balance shown here matches what the agent/orchestration spends against
  (a SOL agent call should reduce it). ✅ / ❌
- A second user's checkout/customer is independent — user A never sees or affects
  user B's subscription or credits. ✅ / ❌

## Security spot-checks

- The Stripe secret key never appears in any API response, log line, or the
  subscription payload (`GET /users/me/subscription` returns only the customer/sub
  ids, never the key). ✅ / ❌
- The browser only ever opens `https://…` Stripe URLs returned by our API. ✅ / ❌
