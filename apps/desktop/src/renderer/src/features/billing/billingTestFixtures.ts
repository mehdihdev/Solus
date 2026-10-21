// Shared fixtures for the Billing component tests (test-only helper).
import { classifyBilling, type BillingView } from './billingState'
import type { BillingSubscription, BillingSummary } from '../../lib/api/resources.billing'

export const NOW = Date.parse('2026-10-19T00:00:00Z')

export const PRICES: NonNullable<BillingSummary['prices']> = [
  { plan: 'basic', interval: 'month', amount_cents: 2500, currency: 'usd' },
  { plan: 'basic', interval: 'year', amount_cents: 20000, currency: 'usd' },
  { plan: 'pro', interval: 'month', amount_cents: 3500, currency: 'usd' },
  { plan: 'pro', interval: 'year', amount_cents: 30000, currency: 'usd' }
]

export const LIVE_SUB: BillingSubscription = {
  user_id: 'u1',
  plan: 'basic',
  status: 'active',
  limits: { max_projects: 3, max_teams: 2, max_integrations: 4 },
  expires_at: null,
  seat_count: 1,
  stripe_subscription_id: 'sub_live',
  billing_interval: 'month',
  current_period_end: '2026-11-19T00:00:00Z',
  cancel_at: null
}

export const LOCAL_TRIAL_SUB: BillingSubscription = {
  ...LIVE_SUB,
  status: 'trialing',
  stripe_subscription_id: null,
  billing_interval: null,
  current_period_end: null,
  expires_at: '2026-10-28T00:00:00Z'
}

export const SUMMARY: BillingSummary = {
  plan: 'basic',
  status: 'active',
  billing_interval: 'month',
  current_period_end: '2026-11-19T00:00:00Z',
  cancel_at: null,
  trial: { state: 'none', ends_at: null },
  next_invoice: { amount_cents: 2500, currency: 'usd', date: '2026-11-19T00:00:00Z' },
  payment_method: { brand: 'visa', last4: '4242' },
  prices: PRICES,
  packs_available: true,
  stripe_status: 'ok'
}

export function viewOf(
  subscription: BillingSubscription | null,
  summary: BillingSummary | null = SUMMARY
): BillingView {
  return classifyBilling({ status: 'ready', subscription, summary, now: NOW })
}
