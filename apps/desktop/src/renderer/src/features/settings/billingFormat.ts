// Pure formatters for the billing summary (SOLUSDEV-86). Kept side-effect-free
// and deterministic (time injected) so the display logic is unit-tested apart
// from the component. Mirrors models.PlanType / SubscriptionStatus / PLAN_LIMITS.
const DAY = 24 * 60 * 60 * 1000

const STATUS_LABELS: Record<string, string> = {
  trialing: 'Trial',
  active: 'Active',
  past_due: 'Past due',
  canceled: 'Canceled'
}

function capitalize(value: string): string {
  return value ? value[0].toUpperCase() + value.slice(1) : value
}

export function planLabel(plan: string): string {
  return capitalize(plan)
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? capitalize(status)
}

/** Whole days until `expiresAt`, rounded up, floored at 0. Null when no expiry. */
export function trialDaysLeft(expiresAt: string | null, now: number = Date.now()): number | null {
  if (!expiresAt) return null
  const t = Date.parse(expiresAt)
  if (Number.isNaN(t)) return null
  return Math.max(0, Math.ceil((t - now) / DAY))
}

/** A plan-limit value: `null` means unlimited (PLAN_LIMITS). */
export function limitLabel(value: number | null): string {
  return value === null ? 'Unlimited' : value.toLocaleString('en-US')
}

export type TrialKind = 'active' | 'ended' | 'none'

export interface TrialInfo {
  kind: TrialKind
  /** Whole days left when active; 0 otherwise. */
  days: number
  endsAt: string | null
}

interface TrialInput {
  status: string
  expires_at: string | null
  trial_expired?: boolean
}

/** Read-time trial state: a trialing row past `expires_at` is `ended` (the
 *  server enforces the same rule; ADR-024). Null/unparsable dates are safe. */
export function trialState(sub: TrialInput, now: number = Date.now()): TrialInfo {
  const endsAt = sub.expires_at
  if (sub.status !== 'trialing') return { kind: 'none', days: 0, endsAt: null }
  if (sub.trial_expired) return { kind: 'ended', days: 0, endsAt }
  const end = endsAt ? Date.parse(endsAt) : Number.NaN
  if (Number.isNaN(end)) return { kind: 'none', days: 0, endsAt: null }
  if (end < now) return { kind: 'ended', days: 0, endsAt }
  return { kind: 'active', days: Math.ceil((end - now) / DAY), endsAt }
}

export function trialEndsLabel(days: number): string {
  return days === 0 ? 'today' : `in ${days} ${days === 1 ? 'day' : 'days'}`
}

export function intervalLabel(interval: 'month' | 'year'): string {
  return interval === 'year' ? 'Yearly' : 'Monthly'
}

function moneyFormat(currency: string, digits: number): Intl.NumberFormat | null {
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: 2
    })
  } catch {
    return null
  }
}

/** `$25.00` — cents precision, for charges. */
export function formatMoney(cents: number, currency: string): string {
  const fmt = moneyFormat(currency, 2)
  const amount = cents / 100
  return fmt ? fmt.format(amount) : `${amount.toFixed(2)} ${currency.toUpperCase()}`
}

/** `$25` for whole-dollar plan prices, `$25.50` otherwise. */
export function formatPlanPrice(cents: number, currency: string): string {
  const fmt = moneyFormat(currency, cents % 100 === 0 ? 0 : 2)
  const amount = cents / 100
  return fmt ? fmt.format(amount) : `${amount.toFixed(2)} ${currency.toUpperCase()}`
}

/** `October 19, 2026` in UTC; an em dash for null/invalid input. */
export function formatDate(iso: string | null | undefined): string {
  const t = iso ? Date.parse(iso) : Number.NaN
  if (Number.isNaN(t)) return '—'
  return new Date(t).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC'
  })
}

/** Mono status chip text on the Billing page: `TRIALING`, `PAST DUE`, `ACTIVE`. */
export function statusChip(status: string): string {
  return status === 'trialing' ? 'TRIALING' : statusLabel(status).toUpperCase()
}
