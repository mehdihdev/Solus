// Billing summary + portal flows (SOLUSDEV-236, API-implementation.md §10).
// Hand-written because the generated schema leaves these response bodies
// untyped. Same injectable-client convention as resources.ts.
import { api, type ApiClient } from './client'
import type { CheckoutSession, PlanType, Subscription } from './resources'

export type BillingInterval = 'month' | 'year'
export type TrialState = 'active' | 'expired' | 'none'
export type StripeStatus = 'ok' | 'unavailable' | 'unconfigured'
export type PortalFlow = 'update' | 'cancel'

export interface BillingPrice {
  plan: PlanType
  interval: BillingInterval
  amount_cents: number
  currency: string
}

/** GET /billing/summary — the only source of Stripe-derived fields. Stripe
 *  fields are null when `stripe_status` is not `ok`. Brand + last four only. */
export interface BillingSummary {
  plan: PlanType
  status: string
  billing_interval: BillingInterval | null
  current_period_end: string | null
  cancel_at: string | null
  trial: { state: TrialState; ends_at: string | null }
  next_invoice: { amount_cents: number; currency: string; date: string } | null
  payment_method: { brand: string; last4: string } | null
  prices: BillingPrice[] | null
  packs_available: boolean
  stripe_status: StripeStatus
}

/** GET /users/me/subscription with the SOLUSDEV-236 additions. */
export interface BillingSubscription extends Subscription {
  billing_interval?: BillingInterval | null
  current_period_end?: string | null
  /** True for a local trial past its `expires_at` (read-time, no job). */
  trial_expired?: boolean
}

export function getBillingSubscription(client: ApiClient = api): Promise<BillingSubscription> {
  return client.request<BillingSubscription>('/users/me/subscription')
}

export function getBillingSummary(client: ApiClient = api): Promise<BillingSummary> {
  return client.request<BillingSummary>('/billing/summary')
}

/** Open the Stripe portal. No `flow` = general portal (no body); `update` /
 *  `cancel` deep-link to the plan-change / cancel screens. */
export function createBillingPortalFlow(
  flow?: PortalFlow,
  client: ApiClient = api
): Promise<CheckoutSession> {
  return client.request<CheckoutSession>('/billing/portal-session', {
    method: 'POST',
    ...(flow ? { body: { flow } } : {})
  })
}
