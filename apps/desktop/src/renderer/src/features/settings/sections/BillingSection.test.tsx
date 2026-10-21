import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BillingSection } from './BillingSection'
import type { SettingsData } from '../useSettingsData'
import type { Subscription } from '../../../lib/api/resources'

const NOW = Date.parse('2026-07-13T00:00:00Z')

const SUB: Subscription = {
  user_id: 'u1',
  plan: 'basic',
  status: 'trialing',
  limits: { max_integrations: 4, max_projects: 3, max_teams: null },
  expires_at: '2026-07-22T00:00:00Z',
  seat_count: 2
}

function data(sub: Subscription | null): SettingsData {
  return {
    status: 'ready',
    profile: null,
    consent: true,
    subscription: sub,
    errors: { sol_mode: null, consent: null, name: null },
    actions: {
      setSolMode: vi.fn(async () => true),
      setConsent: vi.fn(async () => true),
      updateName: vi.fn(async () => true),
      refresh: vi.fn(async () => undefined)
    }
  }
}

describe('BillingSection', () => {
  it('renders the plan and status', () => {
    render(<BillingSection data={data(SUB)} now={NOW} />)
    expect(screen.getByText('Basic')).toBeInTheDocument()
    expect(screen.getByText(/Trial/)).toBeInTheDocument()
  })

  it('shows the trial days remaining', () => {
    render(<BillingSection data={data(SUB)} now={NOW} />)
    expect(screen.getByText(/9 days/)).toBeInTheDocument()
  })

  it('shows the seat count', () => {
    render(<BillingSection data={data(SUB)} now={NOW} />)
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('renders plan limits, with null shown as Unlimited', () => {
    render(<BillingSection data={data(SUB)} now={NOW} />)
    expect(screen.getByText('Integrations')).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
    expect(screen.getByText('Teams')).toBeInTheDocument()
    expect(screen.getByText('Unlimited')).toBeInTheDocument()
  })

  it('renders an empty state when there is no subscription', () => {
    render(<BillingSection data={data(null)} now={NOW} />)
    expect(screen.getByText(/No active subscription/)).toBeInTheDocument()
  })

  it('omits the trial row for an active subscription', () => {
    render(<BillingSection data={data({ ...SUB, status: 'active', expires_at: null })} now={NOW} />)
    expect(screen.queryByText(/days/)).not.toBeInTheDocument()
  })

  it('shows "Trial ended {date}" once the trial has expired (never "today")', () => {
    render(<BillingSection data={data({ ...SUB, expires_at: '2026-07-01T00:00:00Z' })} now={NOW} />)
    expect(screen.getByText('Trial ended')).toBeInTheDocument()
    expect(screen.getByText('July 1, 2026')).toBeInTheDocument()
    expect(screen.queryByText('today')).not.toBeInTheDocument()
    expect(screen.queryByText('Trial ends')).not.toBeInTheDocument()
  })
})
