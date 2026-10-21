import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PlanCards, type PlanCardsProps } from './PlanCards'
import { LIVE_SUB, LOCAL_TRIAL_SUB, SUMMARY, viewOf } from './billingTestFixtures'
import type { BillingSubscription, BillingSummary } from '../../lib/api/resources.billing'

const onSubscribe = vi.fn()
const onPortal = vi.fn()
const contactSalesBridge = vi.fn().mockResolvedValue({ ok: true })

function setup(
  sub: BillingSubscription | null,
  summary: BillingSummary | null = SUMMARY,
  extra: Partial<PlanCardsProps> = {}
): HTMLElement {
  vi.clearAllMocks()
  ;(window as unknown as { solus?: unknown }).solus = {
    billing: { contactSales: contactSalesBridge }
  }
  const { container } = render(
    <PlanCards
      subscription={sub}
      summary={summary}
      view={viewOf(sub, summary)}
      busy={false}
      onSubscribe={onSubscribe}
      onPortal={onPortal}
      {...extra}
    />
  )
  return container
}

function card(name: string): HTMLElement {
  return screen.getByRole('group', { name })
}

describe('PlanCards interval toggle and badge', () => {
  it('badges the current plan only on the toggle interval that matches', async () => {
    setup(LIVE_SUB)
    expect(within(card('Basic')).getByText('CURRENT PLAN')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Yearly' }))
    expect(screen.queryByText('CURRENT PLAN')).not.toBeInTheDocument()
    expect(within(card('Basic')).getByRole('button', { name: 'Change plan' })).toBeInTheDocument()
  })

  it('opens on Yearly for a yearly subscription', () => {
    setup({ ...LIVE_SUB, billing_interval: 'year' }, { ...SUMMARY, billing_interval: 'year' })
    expect(screen.getByRole('button', { name: 'Yearly' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(card('Basic')).getByText('CURRENT PLAN')).toBeInTheDocument()
    expect(within(card('Basic')).getByText('$200')).toBeInTheDocument()
  })

  it('defaults to Monthly without a billing interval', () => {
    setup(LOCAL_TRIAL_SUB)
    expect(screen.getByRole('button', { name: 'Monthly' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('never badges a canceled subscription', () => {
    setup({ ...LIVE_SUB, status: 'canceled' })
    expect(screen.queryByText('CURRENT PLAN')).not.toBeInTheDocument()
  })

  it('never badges Enterprise', () => {
    setup({ ...LIVE_SUB, plan: 'enterprise' })
    expect(within(card('Enterprise')).queryByText('CURRENT PLAN')).not.toBeInTheDocument()
  })
})

describe('PlanCards prices', () => {
  it('shows server prices for the selected interval', async () => {
    setup(LIVE_SUB)
    expect(within(card('Pro')).getByText('$35')).toBeInTheDocument()
    expect(within(card('Pro')).getByText('/ month')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Yearly' }))
    expect(within(card('Pro')).getByText('$300')).toBeInTheDocument()
    expect(within(card('Pro')).getByText('/ year')).toBeInTheDocument()
  })

  it('shows an em dash, never a hard-coded number, when prices are null', () => {
    setup(LIVE_SUB, { ...SUMMARY, prices: null, stripe_status: 'unavailable' })
    expect(within(card('Basic')).getByText('—')).toBeInTheDocument()
    expect(within(card('Pro')).getByText('—')).toBeInTheDocument()
    expect(screen.queryByText('$25')).not.toBeInTheDocument()
  })

  it('shows Custom for Enterprise', () => {
    setup(LIVE_SUB)
    expect(within(card('Enterprise')).getAllByText('Custom')).toHaveLength(4)
  })
})

describe('PlanCards actions', () => {
  it('Stripe-backed subscribers get Change plan -> portal update', async () => {
    setup(LIVE_SUB)
    await userEvent.click(within(card('Pro')).getByRole('button', { name: 'Change plan' }))
    expect(onPortal).toHaveBeenCalledWith('update')
    expect(onSubscribe).not.toHaveBeenCalled()
  })

  it('a local trial gets Subscribe with the plan and selected interval', async () => {
    setup(LOCAL_TRIAL_SUB)
    await userEvent.click(screen.getByRole('button', { name: 'Yearly' }))
    await userEvent.click(within(card('Pro')).getByRole('button', { name: 'Subscribe · Yearly' }))
    expect(onSubscribe).toHaveBeenCalledWith('pro', 'year')
    expect(within(card('Basic')).getByRole('button', { name: /Subscribe/ })).toBeInTheDocument()
  })

  it('a canceled subscription can re-subscribe', () => {
    setup({ ...LIVE_SUB, status: 'canceled' })
    expect(within(card('Pro')).getByRole('button', { name: 'Subscribe · Monthly' })).toBeEnabled()
  })

  it('cancel pending disables the cards and explains why', () => {
    setup({ ...LIVE_SUB, plan: 'pro', cancel_at: '2026-11-19T00:00:00Z' })
    expect(within(card('Basic')).getByRole('button', { name: 'Change plan' })).toBeDisabled()
    expect(screen.getByText('Resume in Manage billing to change plans.')).toBeInTheDocument()
    expect(within(card('Pro')).getByText('CURRENT PLAN')).toBeInTheDocument()
  })

  it('degraded Stripe disables Subscribe but keeps its label', () => {
    setup(LOCAL_TRIAL_SUB, { ...SUMMARY, prices: null, stripe_status: 'unavailable' })
    expect(within(card('Pro')).getByRole('button', { name: /Subscribe/ })).toBeDisabled()
  })

  it('a failed summary disables Change plan for a live subscriber', () => {
    setup(LIVE_SUB, null)
    expect(within(card('Pro')).getByRole('button', { name: 'Change plan' })).toBeDisabled()
  })

  it('busy disables purchase actions', () => {
    setup(LIVE_SUB, SUMMARY, { busy: true })
    expect(within(card('Pro')).getByRole('button', { name: 'Change plan' })).toBeDisabled()
  })
})

describe('PlanCards Contact sales', () => {
  it('is a real button that calls the preload bridge, even while degraded', async () => {
    setup(LIVE_SUB, { ...SUMMARY, prices: null, stripe_status: 'unavailable' })
    const button = within(card('Enterprise')).getByRole('button', { name: 'Contact sales' })
    expect(button).toBeEnabled()
    await userEvent.click(button)
    expect(contactSalesBridge).toHaveBeenCalledTimes(1)
  })

  it('does nothing (and does not throw) without the bridge', async () => {
    setup(LIVE_SUB)
    delete (window as unknown as { solus?: unknown }).solus
    await userEvent.click(screen.getByRole('button', { name: 'Contact sales' }))
    expect(contactSalesBridge).not.toHaveBeenCalled()
  })

  it('renders no anchors or mailto: links anywhere', () => {
    const container = setup(LIVE_SUB)
    expect(container.querySelector('a')).toBeNull()
    expect(container.innerHTML).not.toContain('mailto:')
  })

  it('underlines on hover with the accent border via CSS vars', async () => {
    setup(LIVE_SUB)
    const button = screen.getByRole('button', { name: 'Contact sales' })
    expect(button.style.textDecoration).toBe('none')
    await userEvent.hover(button)
    expect(button.style.textDecoration).toBe('underline')
    expect(button.style.borderColor).toBe('var(--acc)')
    expect(button.style.color).toBe('var(--fg)')
  })
})
