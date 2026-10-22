import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PlanSection } from './PlanSection'
import { subscription } from '../settings.fixtures'

const NOW = Date.parse('2026-10-22T12:00:00Z')
const IN_9_DAYS = new Date(NOW + 9 * 86_400_000).toISOString()
const CREDITS = { balance: 1840, unlimited: false }

describe('PlanSection', () => {
  it('shows the plan, its trial end and the credit balance', () => {
    render(
      <PlanSection
        subscription={subscription({ expires_at: IN_9_DAYS })}
        credits={CREDITS}
        onOpenBilling={vi.fn()}
        now={NOW}
      />
    )
    expect(screen.getByText('Basic')).toBeInTheDocument()
    expect(screen.getByText(/Trial ends in 9 days/)).toBeInTheDocument()
    expect(screen.getByText('1,840')).toBeInTheDocument()
  })

  it('shows each plan limit, Unlimited for null', () => {
    render(
      <PlanSection
        subscription={subscription({ limits: { max_projects: 3, max_teams: null } })}
        credits={CREDITS}
        onOpenBilling={vi.fn()}
      />
    )
    expect(screen.getByText('Projects').nextSibling).toHaveTextContent('Up to 3')
    expect(screen.getByText('Teams').nextSibling).toHaveTextContent('Unlimited')
  })

  it('shows an unknown balance as a dash, and unlimited credits as Unlimited', () => {
    const { rerender } = render(
      <PlanSection
        subscription={subscription()}
        credits={{ balance: null, unlimited: false }}
        onOpenBilling={vi.fn()}
      />
    )
    expect(screen.getByText('Credits').nextSibling).toHaveTextContent('—')
    rerender(
      <PlanSection
        subscription={subscription()}
        credits={{ balance: 0, unlimited: true }}
        onOpenBilling={vi.fn()}
      />
    )
    expect(screen.getByText('Credits').nextSibling).toHaveTextContent('Unlimited')
  })

  it('sends every billing task to the Billing page', async () => {
    const onOpenBilling = vi.fn()
    render(
      <PlanSection subscription={subscription()} credits={CREDITS} onOpenBilling={onOpenBilling} />
    )
    await userEvent.click(screen.getByRole('button', { name: /Open Billing/ }))
    expect(onOpenBilling).toHaveBeenCalled()
  })

  it('says when there is no subscription yet, and still links to Billing', () => {
    render(<PlanSection subscription={null} credits={CREDITS} onOpenBilling={vi.fn()} />)
    expect(screen.getByText(/No active subscription/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Open Billing/ })).toBeInTheDocument()
  })
})
