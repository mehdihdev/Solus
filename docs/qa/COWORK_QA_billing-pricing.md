# Cowork QA — Billing pricing display & plan starting credits (SOLUSDEV-102 follow-up)

Scope: the Billing rail screen now shows real prices and features per plan
(ADR-023, amended 2026-08-08: Basic $25/mo · $200/yr, Pro $35/mo · $300/yr,
Enterprise per-seat/contact sales), dollar prices on credit packs, and the
backend grants one-time plan starting credits (Basic 2,500 / Pro 10,000) via
the Stripe webhook.

## Required setup

- Full dev stack running: `pnpm dev:all` (Postgres, API :8000, desktop app,
  Stripe webhook forwarder — requires `stripe login` done once).
- `packages/api/.env` regenerated from `.env.mega` AFTER the human applied the
  new env lines (pro:month price id + `SOLUS_STRIPE_PACK_USD`), via
  `pnpm env:sync`.
- A signed-in account (Supabase auth) that has NOT previously bought a plan
  (fresh trial account is ideal; signup grants 1,000 trial credits).
- Stripe TEST mode; use card `4242 4242 4242 4242`, any future expiry/CVC.

## Flow 1 — Plan cards show prices and features

1. Open the Billing screen from the rail.
   - [ ] Three plan cards: Basic, Pro, Enterprise.
   - [ ] Basic shows `$25` with `/month`; features "All capabilities" and
         "Starts with 2,500 credits"; limits Projects 3 / Teams 2 / Integrations 4.
   - [ ] Pro shows `$35` with `/month`; "Starts with 10,000 credits"; all limits
         "Unlimited".
   - [ ] Enterprise shows "Custom pricing", per-seat pricing + organization's
         wallet copy, and CONTACT SALES (mailto link) — no Subscribe button.
2. Click the "Yearly" toggle.
   - [ ] Basic shows `$200 /year`, Pro `$300 /year`. Monthly amounts disappear.

## Flow 2 — Credit packs show dollar prices

1. On the same screen, scroll to "Buy credits".
   - [ ] Four packs: 1,000 / 2,500 / 5,000 / 10,000 credits, priced $10 / $25 /
         $50 / $100 respectively (each card shows its dollar price beside Buy).
   - [ ] If `SOLUS_STRIPE_PACK_USD` is NOT configured, cards show credits only
         (no `$undefined` / `$null` artifacts).

## Flow 3 — Subscribing grants plan starting credits (once)

1. Note the current credit balance (fresh account: 1,000).
2. Subscribe to Basic (monthly), complete Stripe test checkout.
   - [ ] Plan card flips to CURRENT PLAN after the webhook lands (may need a
         screen revisit); status reflects the Stripe subscription.
   - [ ] Credit balance becomes 3,500 (1,000 trial + 2,500 Basic grant).
   - [ ] Notifications include "Payment successful"/plan message AND
         "Credits added" mentioning 2,500 credits and the Basic plan.
3. Wait for/trigger any subsequent subscription events (e.g. via Stripe
   dashboard: resend the latest `customer.subscription.updated`).
   - [ ] Balance does NOT increase again (idempotent per user+plan).

## Flow 4 — Upgrade grants the new plan's amount once

1. From a live Basic subscription, switch to Pro via "Switch in portal"
   (billing portal → update plan).
   - [ ] After the webhook lands, balance increases by exactly 10,000 (the Pro
         grant), once.
   - [ ] Plan/limits update to Pro (all unlimited).

## Flow 5 — Pack purchase still works end-to-end

1. Buy the $10 pack (1,000 credits) with the test card.
   - [ ] Balance increases by exactly 1,000 after the webhook lands; a
         "Credits added" notification appears.
   - [ ] Replaying the same webhook event (Stripe dashboard → resend) does not
         double-grant.

## Flow 6 — Cancellation lifecycle (bar, resume, end-of-term downgrade)

1. With a live Pro subscription, open "Manage billing" → cancel the plan
   (at period end) in the Stripe portal, then return to the app.
   - [ ] Billing page auto-refreshes (window focus) and shows a persistent bar:
         "Your Pro plan ends on <date> — you keep full access until then."
   - [ ] A "Subscription canceled" notification appears with the end date.
   - [ ] Limits remain unlimited (access continues until the date).
2. Reopen the portal and undo the cancellation ("renew plan").
   - [ ] The bar disappears on return; a "Subscription resumed" notification
         appears.
3. Cancel again, then simulate the term ending (Stripe test clock, or delete
   the subscription from the Stripe dashboard which fires
   `customer.subscription.deleted`).
   - [ ] Status shows CANCELED; the bar is gone.
   - [ ] Limits clamp to the Basic tier (3 projects / 2 teams / 4 integrations)
         — verify a 4th project is now blocked.
   - [ ] A "Subscription ended" notification appears.
   - [ ] The plan cards offer Subscribe again (no "Switch in portal").
4. Replay/resend any of the above webhook events from the Stripe dashboard.
   - [ ] No duplicate notifications; state unchanged.

## Edge cases / failure paths

- [ ] Signed out: Billing screen shows the honest sign-in notice, no cards.
- [ ] API down: offline notice, no crash.
- [ ] A subscription event that leaves the plan `past_due` (e.g. failed
      payment simulation) does NOT grant starting credits.
- [ ] Enterprise card never offers checkout regardless of state.

## Cross-feature interactions

- [ ] Team/project/integration limit enforcement still reads the subscription
      limits (Basic 3/2/4) after a Basic purchase — try creating a 4th project.
- [ ] SOL agent paid operations still pre-flight against the (now larger)
      balance and debit normally.
