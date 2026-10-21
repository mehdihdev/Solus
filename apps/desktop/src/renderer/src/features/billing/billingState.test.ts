// Pure classifier: one test per wireflow state row (docs/wireflows/billing.md).
import { describe, it, expect } from 'vitest'
import { classifyBilling, type ClassifyInput } from './billingState'
import type { BillingSubscription, BillingSummary } from '../../lib/api/resources.billing'

const NOW = Date.parse('2026-10-19T00:00:00Z')

const SUB: BillingSubscription = {
  user_id: 'u1',
  plan: 'basic',
  status: 'active',
  limits: {},
  expires_at: null,
  seat_count: 1,
  stripe_subscription_id: 'sub_live',
  billing_interval: 'month',
  current_period_end: '2026-11-19T00:00:00Z'
}

const SUMMARY: BillingSummary = {
  plan: 'basic',
  status: 'active',
  billing_interval: 'month',
  current_period_end: '2026-11-19T00:00:00Z',
  cancel_at: null,
  trial: { state: 'none', ends_at: null },
  next_invoice: { amount_cents: 2500, currency: 'usd', date: '2026-11-19T00:00:00Z' },
  payment_method: { brand: 'visa', last4: '4242' },
  prices: [],
  packs_available: true,
  stripe_status: 'ok'
}

function view(
  sub: Partial<BillingSubscription> | null,
  summary: Partial<BillingSummary> | null = {},
  status: ClassifyInput['status'] = 'ready'
): ReturnType<typeof classifyBilling> {
  return classifyBilling({
    status,
    subscription: sub === null ? null : { ...SUB, ...sub },
    summary: summary === null ? null : { ...SUMMARY, ...summary },
    now: NOW
  })
}

const LOCAL = { stripe_subscription_id: null, billing_interval: null, current_period_end: null }

describe('classifyBilling precedence', () => {
  it('offline beats loading and everything else', () => {
    expect(view(SUB, {}, 'offline').kind).toBe('offline')
  })
  it('loading comes before the subscription fields', () => {
    expect(view(null, null, 'loading').kind).toBe('loading')
  })
})

describe('classifyBilling states', () => {
  it('3: local trial active has no banner and Subscribe semantics', () => {
    const v = view(
      { ...LOCAL, status: 'trialing', expires_at: '2026-10-25T00:00:00Z' },
      { trial: { state: 'active', ends_at: '2026-10-25T00:00:00Z' } }
    )
    expect(v).toMatchObject({ kind: 'local_trial_active', banner: null, isLive: false })
    expect(v.showPlanActions).toBe(false)
    expect(v.trial.kind).toBe('active')
  })

  it('4: local trial expired warns with the end date', () => {
    const v = view(
      { ...LOCAL, status: 'trialing', expires_at: '2026-10-10T00:00:00Z', trial_expired: true },
      { trial: { state: 'expired', ends_at: '2026-10-10T00:00:00Z' } }
    )
    expect(v.kind).toBe('local_trial_expired')
    expect(v.banner).toEqual({
      level: 'warn',
      text: 'Trial ended October 10, 2026 — choose a plan'
    })
  })

  it('4: expiry is detected from expires_at alone when the summary failed', () => {
    const v = view({ ...LOCAL, status: 'trialing', expires_at: '2026-10-10T00:00:00Z' }, null)
    expect(v.kind).toBe('local_trial_expired')
  })

  it('5: Stripe trialing is live with Change/Cancel', () => {
    const v = view({ status: 'trialing', expires_at: '2026-10-25T00:00:00Z' })
    expect(v).toMatchObject({ kind: 'stripe_trialing', isLive: true, showPlanActions: true })
    expect(v.banner).toBeNull()
  })

  it('6/7: active is live with Change/Cancel and defaults to its interval', () => {
    expect(view({}).defaultInterval).toBe('month')
    const yearly = view({ billing_interval: 'year' })
    expect(yearly).toMatchObject({ kind: 'active', showPlanActions: true, defaultInterval: 'year' })
  })

  it('interval defaults to month when none is known', () => {
    expect(view({ ...LOCAL, status: 'trialing', expires_at: null }).defaultInterval).toBe('month')
  })

  it('8: cancel pending disables cards and hides Change plan', () => {
    const v = view({ cancel_at: '2026-11-19T00:00:00Z' })
    expect(v).toMatchObject({ kind: 'cancel_pending', cancelPending: true, isLive: true })
    expect(v.showPlanActions).toBe(false)
  })

  it('9: canceled is not live and shows no plan actions', () => {
    const v = view({ status: 'canceled' })
    expect(v).toMatchObject({ kind: 'canceled', isLive: false, showPlanActions: false })
    expect(v.banner).toBeNull()
  })

  it('10: past due warns about the failed payment and keeps Change/Cancel', () => {
    const v = view({ status: 'past_due' })
    expect(v.kind).toBe('past_due')
    expect(v.banner).toEqual({
      level: 'warn',
      text: 'Payment failed — update your payment method in Manage billing to keep your plan.'
    })
    expect(v.showPlanActions).toBe(true)
  })

  it('11: Stripe unavailable warns and disables purchases', () => {
    const v = view({}, { stripe_status: 'unavailable' })
    expect(v.degraded).toBe('unavailable')
    expect(v.purchasesDisabled).toBe(true)
    expect(v.banner).toEqual({
      level: 'warn',
      text: 'Billing is temporarily unavailable — your plan is unchanged. Try again in a few minutes.'
    })
  })

  it('11: a failed summary fetch degrades locally to unavailable', () => {
    const v = view({}, null)
    expect(v.degraded).toBe('unavailable')
    expect(v.purchasesDisabled).toBe(true)
  })

  it('12: unconfigured is an info banner and disables purchases', () => {
    const v = view({}, { stripe_status: 'unconfigured' })
    expect(v.degraded).toBe('unconfigured')
    expect(v.purchasesDisabled).toBe(true)
    expect(v.banner).toEqual({
      level: 'info',
      text: "Billing isn't configured for this environment."
    })
  })

  it('degraded banner outranks past due and trial expired (one banner only)', () => {
    expect(view({ status: 'past_due' }, { stripe_status: 'unavailable' }).banner?.level).toBe(
      'warn'
    )
    expect(view({ status: 'past_due' }, { stripe_status: 'unavailable' }).banner?.text).toMatch(
      /temporarily unavailable/
    )
  })

  it('13: packs flag does not change the plan state', () => {
    const v = view({}, { packs_available: false })
    expect(v.kind).toBe('active')
    expect(v.purchasesDisabled).toBe(false)
  })

  it('no subscription row classifies as none (Subscribe, not live)', () => {
    expect(view(null)).toMatchObject({ kind: 'no_subscription', isLive: false })
  })
})
