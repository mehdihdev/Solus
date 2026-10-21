// Pure classifier for the Billing screen (docs/wireflows/billing.md §States).
// First match wins: offline, loading, then subscription fields. Stripe
// degradation (summary unavailable/unconfigured, or the summary fetch failed)
// is an overlay flag, not a plan state: it disables purchase actions.
import { formatDate, trialState, type TrialInfo } from '../settings/billingFormat'
import type {
  BillingInterval,
  BillingSubscription,
  BillingSummary,
  StripeStatus
} from '../../lib/api/resources.billing'

export type BillingStateKind =
  | 'offline'
  | 'loading'
  | 'no_subscription'
  | 'local_trial_active'
  | 'local_trial_expired'
  | 'stripe_trialing'
  | 'active'
  | 'cancel_pending'
  | 'canceled'
  | 'past_due'

export interface BillingBannerSpec {
  level: 'warn' | 'info'
  text: string
}

export interface BillingView {
  kind: BillingStateKind
  banner: BillingBannerSpec | null
  degraded: StripeStatus
  /** Stripe-backed live subscription (plan changes go through the portal). */
  isLive: boolean
  /** Show Change plan / Cancel plan in the current-plan card. */
  showPlanActions: boolean
  cancelPending: boolean
  /** Subscribe / Change plan / Manage billing / pack buttons are disabled. */
  purchasesDisabled: boolean
  trial: TrialInfo
  defaultInterval: BillingInterval
}

export interface ClassifyInput {
  status: 'loading' | 'ready' | 'offline'
  subscription: BillingSubscription | null
  /** null once loaded = the summary request failed (degrades locally). */
  summary: BillingSummary | null
  now: number
}

const LIVE_STATUSES = ['active', 'trialing', 'past_due']

const UNAVAILABLE_COPY =
  'Billing is temporarily unavailable — your plan is unchanged. Try again in a few minutes.'
const UNCONFIGURED_COPY = "Billing isn't configured for this environment."
const PAST_DUE_COPY =
  'Payment failed — update your payment method in Manage billing to keep your plan.'

const NONE: TrialInfo = { kind: 'none', days: 0, endsAt: null }

function kindOf(sub: BillingSubscription | null, trial: TrialInfo): BillingStateKind {
  if (!sub) return 'no_subscription'
  if (sub.status === 'canceled') return 'canceled'
  if (sub.cancel_at && (sub.status === 'active' || sub.status === 'trialing')) {
    return 'cancel_pending'
  }
  if (sub.status === 'past_due') return 'past_due'
  if (sub.status === 'trialing') {
    if (sub.stripe_subscription_id) return 'stripe_trialing'
    return trial.kind === 'ended' ? 'local_trial_expired' : 'local_trial_active'
  }
  return 'active'
}

function bannerFor(
  kind: BillingStateKind,
  degraded: StripeStatus,
  trial: TrialInfo
): BillingBannerSpec | null {
  if (degraded === 'unavailable') return { level: 'warn', text: UNAVAILABLE_COPY }
  if (degraded === 'unconfigured') return { level: 'info', text: UNCONFIGURED_COPY }
  if (kind === 'past_due') return { level: 'warn', text: PAST_DUE_COPY }
  if (kind === 'local_trial_expired') {
    return { level: 'warn', text: `Trial ended ${formatDate(trial.endsAt)} — choose a plan` }
  }
  return null
}

function placeholder(kind: 'offline' | 'loading'): BillingView {
  return {
    kind,
    banner: null,
    degraded: 'ok',
    isLive: false,
    showPlanActions: false,
    cancelPending: false,
    purchasesDisabled: false,
    trial: NONE,
    defaultInterval: 'month'
  }
}

export function classifyBilling(input: ClassifyInput): BillingView {
  const { status, subscription: sub, summary, now } = input
  if (status === 'offline') return placeholder('offline')
  if (status === 'loading') return placeholder('loading')
  const local = sub ? trialState(sub, now) : NONE
  const trial =
    summary?.trial.state === 'expired' && sub?.status === 'trialing'
      ? { ...local, kind: 'ended' as const, endsAt: summary.trial.ends_at ?? local.endsAt }
      : local
  const kind = kindOf(sub, trial)
  const degraded: StripeStatus = summary ? summary.stripe_status : 'unavailable'
  const isLive =
    !!sub?.stripe_subscription_id && kind !== 'canceled' && LIVE_STATUSES.includes(sub.status)
  const cancelPending = kind === 'cancel_pending'
  return {
    kind,
    banner: bannerFor(kind, degraded, trial),
    degraded,
    isLive,
    showPlanActions: isLive && !cancelPending,
    cancelPending,
    purchasesDisabled: degraded !== 'ok',
    trial,
    defaultInterval: sub?.billing_interval ?? summary?.billing_interval ?? 'month'
  }
}
