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
