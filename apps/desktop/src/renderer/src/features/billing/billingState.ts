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
  /** ADR-042: the free Academic plan, live or past its `expires_at`. */
  | 'academic'
  | 'academic_expired'

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

function academicKind(sub: BillingSubscription, now: number): BillingStateKind {
  const ends = sub.expires_at ? Date.parse(sub.expires_at) : Number.NaN
  return !Number.isNaN(ends) && ends <= now ? 'academic_expired' : 'academic'
}

/** A live subscription with a scheduled end: cancelled, running out at `cancel_at`. */
function isCancelPending(sub: BillingSubscription): boolean {
  return Boolean(sub.cancel_at) && (sub.status === 'active' || sub.status === 'trialing')
}

/** A trialing subscription: Stripe's trial when it has a Stripe id, else the local one. */
function trialingKind(sub: BillingSubscription, trial: TrialInfo): BillingStateKind {
  if (sub.stripe_subscription_id) return 'stripe_trialing'
  return trial.kind === 'ended' ? 'local_trial_expired' : 'local_trial_active'
}

function kindOf(sub: BillingSubscription | null, trial: TrialInfo, now: number): BillingStateKind {
  if (!sub) return 'no_subscription'
  if (sub.plan === 'academic' && sub.status === 'active') return academicKind(sub, now)
  if (sub.status === 'canceled') return 'canceled'
  if (isCancelPending(sub)) return 'cancel_pending'
  if (sub.status === 'past_due') return 'past_due'
  if (sub.status === 'trialing') return trialingKind(sub, trial)
  return 'active'
}

function bannerFor(
  kind: BillingStateKind,
  degraded: StripeStatus,
  trial: TrialInfo,
  sub: BillingSubscription | null
): BillingBannerSpec | null {
  if (degraded === 'unavailable') return { level: 'warn', text: UNAVAILABLE_COPY }
  if (degraded === 'unconfigured') return { level: 'info', text: UNCONFIGURED_COPY }
  if (kind === 'past_due') return { level: 'warn', text: PAST_DUE_COPY }
  if (kind === 'local_trial_expired') {
    return { level: 'warn', text: `Trial ended ${formatDate(trial.endsAt)} — choose a plan` }
  }
  if (kind === 'academic_expired') {
    return {
      level: 'warn',
      text: `Academic plan ended ${formatDate(sub?.expires_at)} — verify your academic email again or choose a plan`
    }
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

/** Stripe's expired-trial verdict outranks the local clock on a trialing sub. */
function effectiveTrial(
  sub: ClassifyInput['subscription'],
  summary: ClassifyInput['summary'],
  now: ClassifyInput['now']
): TrialInfo {
  const local = sub ? trialState(sub, now) : NONE
  if (summary?.trial.state !== 'expired' || sub?.status !== 'trialing') return local
  return { ...local, kind: 'ended', endsAt: summary.trial.ends_at ?? local.endsAt }
}

function isLiveSub(sub: ClassifyInput['subscription'], kind: BillingView['kind']): boolean {
  return !!sub?.stripe_subscription_id && kind !== 'canceled' && LIVE_STATUSES.includes(sub.status)
}

export function classifyBilling(input: ClassifyInput): BillingView {
  const { status, subscription: sub, summary, now } = input
  if (status === 'offline') return placeholder('offline')
  if (status === 'loading') return placeholder('loading')
  const trial = effectiveTrial(sub, summary, now)
  const kind = kindOf(sub, trial, now)
  const degraded: StripeStatus = summary ? summary.stripe_status : 'unavailable'
  const isLive = isLiveSub(sub, kind)
  const cancelPending = kind === 'cancel_pending'
  return {
    kind,
    banner: bannerFor(kind, degraded, trial, sub),
    degraded,
    isLive,
    showPlanActions: isLive && !cancelPending,
    cancelPending,
    purchasesDisabled: degraded !== 'ok',
    trial,
    defaultInterval: sub?.billing_interval ?? summary?.billing_interval ?? 'month'
  }
}
