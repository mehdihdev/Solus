import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CurrentPlanCard } from './CurrentPlanCard'
import { LIVE_SUB, LOCAL_TRIAL_SUB, SUMMARY, viewOf } from './billingTestFixtures'
import type { BillingSubscription, BillingSummary } from '../../lib/api/resources.billing'

const onPortal = vi.fn()
const onBuyMore = vi.fn()

function setup(
  sub: BillingSubscription | null,
  summary: BillingSummary | null = SUMMARY,
  extra: { unlimited?: boolean; credits?: number | null; busy?: boolean } = {}
): void {
  vi.clearAllMocks()
  render(
    <CurrentPlanCard
      subscription={sub}
      summary={summary}
      view={viewOf(sub, summary)}
      credits={extra.credits === undefined ? 9059 : extra.credits}
      unlimited={extra.unlimited ?? false}
      busy={extra.busy ?? false}
      onPortal={onPortal}
      onBuyMore={onBuyMore}
    />
  )
}

function row(label: string): string {
  const el = screen.getByText(label)
  return el.parentElement?.textContent ?? ''
}

describe('CurrentPlanCard Buy more (SOLUSDEV-325)', () => {
  it('the Credits row links down to the Credits section', async () => {
    setup(LIVE_SUB)
    await userEvent.click(screen.getByRole('button', { name: /buy more/i }))
    expect(onBuyMore).toHaveBeenCalled()
  })

  it('has no Buy more for unlimited development accounts', () => {
    setup(LIVE_SUB, SUMMARY, { unlimited: true })
    expect(screen.queryByRole('button', { name: /buy more/i })).not.toBeInTheDocument()
  })
})

describe('CurrentPlanCard rows', () => {
  it('active: renews date, next charge, card, credits, seats', () => {
    setup(LIVE_SUB)
    expect(screen.getByText('Basic plan')).toBeInTheDocument()
    expect(screen.getByText('ACTIVE')).toBeInTheDocument()
    expect(row('Renews')).toContain('November 19, 2026')
    expect(row('Next charge')).toContain('$25.00 on November 19, 2026')
    expect(row('Card')).toContain('Visa •••• 4242')
    expect(row('Credits')).toContain('9,059')
    expect(row('Seats')).toContain('1')
  })

  it('local trial active: Trial ends in N days, no charge, no card, no Change/Cancel', () => {
    setup(LOCAL_TRIAL_SUB, { ...SUMMARY, next_invoice: null, payment_method: null })
    expect(screen.getByText('TRIALING')).toBeInTheDocument()
    expect(row('Trial ends')).toContain('in 9 days')
    expect(row('Next charge')).toContain('—')
    expect(row('Card')).toContain('No card on file')
    expect(screen.queryByRole('button', { name: 'Change plan' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel plan' })).not.toBeInTheDocument()
  })

  it('local trial expired: Trial ended row replaces Trial ends', () => {
    setup(
      { ...LOCAL_TRIAL_SUB, expires_at: '2026-10-10T00:00:00Z', trial_expired: true },
      { ...SUMMARY, next_invoice: null, payment_method: null }
    )
    expect(row('Trial ended')).toContain('October 10, 2026')
    expect(screen.queryByText('Trial ends')).not.toBeInTheDocument()
  })

  it('Stripe trialing: shows the trial end and the first charge', () => {
    setup({ ...LIVE_SUB, status: 'trialing', expires_at: '2026-10-25T00:00:00Z' })
    expect(row('Trial ends')).toContain('October 25, 2026, then $25.00 on November 19, 2026')
    expect(screen.getByRole('button', { name: 'Change plan' })).toBeInTheDocument()
  })

  it('cancel pending: Ends row, no Change plan, Resume hint instead of Cancel plan', () => {
    setup({ ...LIVE_SUB, cancel_at: '2026-11-19T00:00:00Z' }, { ...SUMMARY, next_invoice: null })
    expect(row('Ends')).toContain('November 19, 2026')
    expect(screen.queryByText('Renews')).not.toBeInTheDocument()
    expect(row('Next charge')).toContain('None — plan ends November 19, 2026')
    expect(screen.queryByRole('button', { name: 'Change plan' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel plan' })).not.toBeInTheDocument()
    expect(screen.getByText('Resume in Manage billing')).toBeInTheDocument()
  })

  it('canceled: No active plan headline and the ended date', () => {
    setup({ ...LIVE_SUB, status: 'canceled' }, { ...SUMMARY, next_invoice: null })
    expect(screen.getByText('No active plan')).toBeInTheDocument()
    expect(screen.getByText('Your plan ended November 19, 2026')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Change plan' })).not.toBeInTheDocument()
  })

  it('canceled without a period end shows no date', () => {
    setup(
      { ...LIVE_SUB, status: 'canceled', current_period_end: null },
      { ...SUMMARY, current_period_end: null }
    )
    expect(screen.getByText('Your plan ended')).toBeInTheDocument()
  })

  it('past due: PAST DUE chip, Change/Cancel shown, next charge dash', () => {
    setup({ ...LIVE_SUB, status: 'past_due' }, { ...SUMMARY, next_invoice: null })
    expect(screen.getByText('PAST DUE')).toBeInTheDocument()
    expect(row('Next charge')).toContain('—')
    expect(screen.getByRole('button', { name: 'Cancel plan' })).toBeInTheDocument()
  })

  it('Stripe unavailable: local fields stay, Stripe rows say Unavailable right now', () => {
    setup(LIVE_SUB, null)
    expect(row('Renews')).toContain('November 19, 2026')
    expect(row('Next charge')).toContain('Unavailable right now')
    expect(row('Card')).toContain('Unavailable right now')
  })

  it('unlimited (development) credits and a null balance', () => {
    setup(LIVE_SUB, SUMMARY, { unlimited: true })
    expect(screen.getByText('Unlimited (development)')).toBeInTheDocument()
  })

  it('shows a dash while credits are unknown', () => {
    setup(LIVE_SUB, SUMMARY, { credits: null })
    expect(row('Credits')).toContain('—')
  })

  it('without a subscription: the empty-state copy (or unlimited development)', () => {
    setup(null)
    expect(screen.getByText(/No active subscription on this account yet/)).toBeInTheDocument()
  })
})

describe('CurrentPlanCard actions', () => {
  it('Manage billing opens the general portal', async () => {
    setup(LIVE_SUB)
    await userEvent.click(screen.getByRole('button', { name: 'Manage billing' }))
    expect(onPortal).toHaveBeenCalledWith(undefined)
  })

  it('Change plan opens the update flow, Cancel plan the cancel flow', async () => {
    setup(LIVE_SUB)
    await userEvent.click(screen.getByRole('button', { name: 'Change plan' }))
    expect(onPortal).toHaveBeenLastCalledWith('update')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel plan' }))
    expect(onPortal).toHaveBeenLastCalledWith('cancel')
  })

  it('every portal action is disabled while Stripe is degraded or busy', () => {
    setup(LIVE_SUB, null)
    for (const name of ['Manage billing', 'Change plan', 'Cancel plan']) {
      expect(screen.getByRole('button', { name })).toBeDisabled()
    }
  })
})

describe('CurrentPlanCard academic plan (ADR-042)', () => {
  const ACADEMIC: BillingSubscription = {
    ...LOCAL_TRIAL_SUB,
    plan: 'academic',
    status: 'active',
    expires_at: '2027-10-19T00:00:00Z'
  }
  const ACADEMIC_SUMMARY: BillingSummary = { ...SUMMARY, plan: 'academic', next_invoice: null }

  it('shows the free plan with its end date and no Stripe plan actions', () => {
    setup(ACADEMIC, ACADEMIC_SUMMARY)
    expect(screen.getByText('Academic plan')).toBeInTheDocument()
    expect(screen.getByText('ACTIVE')).toBeInTheDocument()
    expect(row('Free until')).toContain('October 19, 2027')
    expect(row('Next charge')).toContain('None — Academic is free')
    expect(screen.queryByRole('button', { name: 'Change plan' })).not.toBeInTheDocument()
  })

  it('marks an ended academic plan', () => {
    setup({ ...ACADEMIC, expires_at: '2026-10-01T00:00:00Z' }, ACADEMIC_SUMMARY)
    expect(screen.getByText('EXPIRED')).toBeInTheDocument()
    expect(row('Ended')).toContain('October 1, 2026')
  })
})
