import { describe, it, expect } from 'vitest'
import {
  planLabel,
  statusLabel,
  trialDaysLeft,
  limitLabel,
  trialState,
  trialEndsLabel,
  intervalLabel,
  formatMoney,
  formatPlanPrice,
  formatDate,
  statusChip
} from './billingFormat'

describe('planLabel', () => {
  it('titles the known plans', () => {
    expect(planLabel('basic')).toBe('Basic')
    expect(planLabel('pro')).toBe('Pro')
    expect(planLabel('enterprise')).toBe('Enterprise')
  })

  it('capitalizes an unknown plan defensively', () => {
    expect(planLabel('startup')).toBe('Startup')
  })
})

describe('statusLabel', () => {
  it('maps subscription statuses to friendly labels', () => {
    expect(statusLabel('trialing')).toBe('Trial')
    expect(statusLabel('active')).toBe('Active')
    expect(statusLabel('past_due')).toBe('Past due')
    expect(statusLabel('canceled')).toBe('Canceled')
  })
})

describe('trialDaysLeft', () => {
  const now = Date.parse('2026-07-13T00:00:00Z')

  it('returns whole days remaining, rounded up', () => {
    expect(trialDaysLeft('2026-07-22T00:00:00Z', now)).toBe(9)
    expect(trialDaysLeft('2026-07-13T12:00:00Z', now)).toBe(1)
  })

  it('never returns a negative number', () => {
    expect(trialDaysLeft('2026-07-01T00:00:00Z', now)).toBe(0)
  })

  it('returns null when there is no expiry', () => {
    expect(trialDaysLeft(null, now)).toBeNull()
  })
})

describe('limitLabel', () => {
  it('renders null as unlimited', () => {
    expect(limitLabel(null)).toBe('Unlimited')
  })

  it('renders a number with grouping', () => {
    expect(limitLabel(4)).toBe('4')
    expect(limitLabel(5000)).toBe('5,000')
  })
})

describe('trialState', () => {
  const now = Date.parse('2026-07-13T00:00:00Z')
  const base = { status: 'trialing', expires_at: '2026-07-22T00:00:00Z' }

  it('is active with whole days left for a future expiry', () => {
    expect(trialState(base, now)).toEqual({
      kind: 'active',
      days: 9,
      endsAt: '2026-07-22T00:00:00Z'
    })
  })

  it('is ended once expires_at is past (never "today" forever)', () => {
    const state = trialState({ ...base, expires_at: '2026-07-01T00:00:00Z' }, now)
    expect(state.kind).toBe('ended')
    expect(state.endsAt).toBe('2026-07-01T00:00:00Z')
  })

  it('is ended when the server flags trial_expired, even without a date', () => {
    expect(trialState({ ...base, expires_at: null, trial_expired: true }, now).kind).toBe('ended')
  })

  it('is none without an expiry, with an unparsable one, or when not trialing', () => {
    expect(trialState({ ...base, expires_at: null }, now).kind).toBe('none')
    expect(trialState({ ...base, expires_at: 'garbage' }, now).kind).toBe('none')
    expect(trialState({ status: 'active', expires_at: base.expires_at }, now).kind).toBe('none')
  })
})

describe('trialEndsLabel', () => {
  it('words the remaining time', () => {
    expect(trialEndsLabel(0)).toBe('today')
    expect(trialEndsLabel(1)).toBe('in 1 day')
    expect(trialEndsLabel(9)).toBe('in 9 days')
  })
})

describe('intervalLabel', () => {
  it('names the intervals', () => {
    expect(intervalLabel('month')).toBe('Monthly')
    expect(intervalLabel('year')).toBe('Yearly')
  })
})

describe('formatMoney', () => {
  it('shows cents precision in the stated currency', () => {
    expect(formatMoney(2500, 'usd')).toBe('$25.00')
    expect(formatMoney(1999, 'USD')).toBe('$19.99')
  })

  it('falls back to a plain amount for an unknown currency code', () => {
    expect(formatMoney(2500, 'not-a-code')).toBe('25.00 NOT-A-CODE')
  })
})

describe('formatPlanPrice', () => {
  it('drops .00 for whole-dollar prices', () => {
    expect(formatPlanPrice(2500, 'usd')).toBe('$25')
    expect(formatPlanPrice(20000, 'usd')).toBe('$200')
    expect(formatPlanPrice(2550, 'usd')).toBe('$25.50')
  })
})

describe('formatDate', () => {
  it('formats in UTC as a long date', () => {
    expect(formatDate('2026-10-19T23:59:00Z')).toBe('October 19, 2026')
  })

  it('returns an em dash for null or invalid input', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate('nope')).toBe('—')
  })
})

describe('statusChip', () => {
  it('uppercases the status, spelling out TRIALING', () => {
    expect(statusChip('trialing')).toBe('TRIALING')
    expect(statusChip('past_due')).toBe('PAST DUE')
    expect(statusChip('active')).toBe('ACTIVE')
  })
})
