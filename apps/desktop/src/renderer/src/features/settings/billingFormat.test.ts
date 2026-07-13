import { describe, it, expect } from 'vitest'
import { planLabel, statusLabel, trialDaysLeft, limitLabel } from './billingFormat'

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
