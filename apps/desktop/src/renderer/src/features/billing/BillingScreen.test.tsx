// Billing screen: current plan + credits summary, Stripe checkout, interval
// toggle, credit packs, billing portal, and the offline notice.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BillingScreen } from './BillingScreen'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getSubscription: vi.fn(),
    getCredits: vi.fn(),
    getCreditPacks: vi.fn(),
    createSubscriptionCheckout: vi.fn(),
    createPackCheckout: vi.fn(),
    createBillingPortal: vi.fn()
  }
})

const SUB: resources.Subscription = {
  user_id: 'u1',
  plan: 'basic',
  status: 'trialing',
  limits: { max_projects: 3, max_teams: 2, max_integrations: 4 },
  expires_at: '2026-08-01T00:00:00Z',
  seat_count: 1
}

const openExternal = vi.fn().mockResolvedValue({ ok: true })

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.com' } })
  vi.mocked(resources.getSubscription).mockResolvedValue(SUB)
  vi.mocked(resources.getCredits).mockResolvedValue({ user_id: 'u1', balance: 1000 })
  vi.mocked(resources.getCreditPacks).mockResolvedValue([{ price_id: 'price_p10', credits: 500 }])
  vi.mocked(resources.createSubscriptionCheckout).mockResolvedValue({ url: 'https://checkout/x' })
  vi.mocked(resources.createPackCheckout).mockResolvedValue({ url: 'https://checkout/pack' })
  vi.mocked(resources.createBillingPortal).mockResolvedValue({ url: 'https://portal/x' })
  ;(window as unknown as { solus?: unknown }).solus = { billing: { openExternal } }
})

afterEach(() => {
  delete (window as unknown as { solus?: unknown }).solus
})

describe('BillingScreen', () => {
  billingSummaryTests()
  billingCheckoutTests()
  billingPlanDetailsTests()
  billingCancellationAndPacksTests()
})

function billingSummaryTests(): void {
  it('shows the current plan, status, and credits', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Billing')).toBeInTheDocument())
    expect(screen.getByText('Basic')).toBeInTheDocument()
    expect(screen.getByText('TRIAL')).toBeInTheDocument()
    expect(screen.getByText('1,000')).toBeInTheDocument() // credit balance
  })

  it.each([true, false])(
    'shows the development allowance only when flagged (%s)',
    async (unlimited) => {
      vi.mocked(resources.getCredits).mockResolvedValue({ user_id: 'u1', balance: 17, unlimited })
      render(<BillingScreen />)
      await screen.findByText(unlimited ? 'Unlimited (development)' : '17')
      expect(
        screen.queryByText(unlimited ? '17' : 'Unlimited (development)')
      ).not.toBeInTheDocument()
    }
  )

  it('shows the development allowance without a subscription', async () => {
    vi.mocked(resources.getSubscription).mockRejectedValue(new Error('404'))
    vi.mocked(resources.getCredits).mockResolvedValue({
      user_id: 'u1',
      balance: 0,
      unlimited: true
    })
    render(<BillingScreen />)
    await screen.findByText('Unlimited (development)')
  })

  it('shows an honest offline notice when signed out', async () => {
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    render(<BillingScreen />)
    await waitFor(() =>
      expect(screen.getByText(/Sign in to Solus to manage billing/)).toBeInTheDocument()
    )
  })
}

function billingCheckoutTests(): void {
  it('opens Stripe Checkout for the chosen plan (monthly by default)', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /Subscribe/i }))
    await waitFor(() =>
      expect(resources.createSubscriptionCheckout).toHaveBeenCalledWith('pro', 'month')
    )
    expect(openExternal).toHaveBeenCalledWith('https://checkout/x')
  })

  it('honours the yearly interval toggle', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Yearly' }))
    await userEvent.click(screen.getByRole('button', { name: /Subscribe/i }))
    await waitFor(() =>
      expect(resources.createSubscriptionCheckout).toHaveBeenCalledWith('pro', 'year')
    )
  })

  it('buys a credit pack via Stripe Checkout', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Buy credits')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Buy' }))
    await waitFor(() => expect(resources.createPackCheckout).toHaveBeenCalledWith('price_p10'))
  })

  it('opens the billing portal', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /Manage billing/i }))
    await waitFor(() => expect(resources.createBillingPortal).toHaveBeenCalled())
    expect(openExternal).toHaveBeenCalledWith('https://portal/x')
  })

  it('routes an existing Stripe subscriber to the portal instead of a second checkout', async () => {
    vi.mocked(resources.getSubscription).mockResolvedValue({
      ...SUB,
      status: 'active',
      stripe_subscription_id: 'sub_live'
    })
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    // No "Subscribe" button for a live subscriber; plan changes go to the portal.
    expect(screen.queryByRole('button', { name: /Subscribe/i })).not.toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: /Switch in portal/i })[0])
    await waitFor(() => expect(resources.createBillingPortal).toHaveBeenCalled())
    expect(resources.createSubscriptionCheckout).not.toHaveBeenCalled()
  })
}

function billingPlanDetailsTests(): void {
  it('marks the active plan as current (not subscribable)', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    // Only the Pro card offers Subscribe; Basic (current) shows CURRENT PLAN.
    expect(screen.getAllByRole('button', { name: /Subscribe/i })).toHaveLength(1)
  })

  it('shows monthly prices on the plan cards (ADR-023)', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    expect(screen.getByText('$25')).toBeInTheDocument()
    expect(screen.getByText('$35')).toBeInTheDocument()
    expect(screen.getAllByText('/month')).toHaveLength(2)
  })

  it('switches to yearly prices with the interval toggle', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Yearly' }))
    expect(screen.getByText('$200')).toBeInTheDocument()
    expect(screen.getByText('$300')).toBeInTheDocument()
    expect(screen.queryByText('$25')).not.toBeInTheDocument()
  })

  it('lists the plan features including starting credits (ADR-024)', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    expect(screen.getAllByText('All capabilities')).toHaveLength(2)
    expect(screen.getByText(/Starts with 2,500 credits/)).toBeInTheDocument()
    expect(screen.getByText(/Starts with 10,000 credits/)).toBeInTheDocument()
  })

  it('presents Enterprise as per-seat, org-paid, contact sales', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    expect(screen.getByText(/Per-seat pricing/)).toBeInTheDocument()
    expect(screen.getByText(/organization('|’)s wallet/i)).toBeInTheDocument()
    expect(screen.getByText('CONTACT SALES')).toBeInTheDocument()
  })
}

function billingCancellationAndPacksTests(): void {
  it('shows a persistent end-date bar while a cancellation is pending', async () => {
    vi.mocked(resources.getSubscription).mockResolvedValue({
      ...SUB,
      plan: 'pro',
      status: 'active',
      stripe_subscription_id: 'sub_live',
      cancel_at: '2026-09-15T00:00:00Z'
    })
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Billing')).toBeInTheDocument())
    const bar = screen.getByRole('status')
    expect(bar.textContent).toMatch(/Pro plan ends on/i)
    expect(bar.textContent).toMatch(/September 15, 2026/)
    expect(bar.textContent).toMatch(/keep full access until then/i)
  })

  it('shows no end-date bar without a pending cancellation or once canceled', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Billing')).toBeInTheDocument())
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    vi.mocked(resources.getSubscription).mockResolvedValue({
      ...SUB,
      status: 'canceled',
      cancel_at: null
    })
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getAllByText('Billing').length).toBeGreaterThan(0))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows the dollar price on credit packs when the server provides it', async () => {
    vi.mocked(resources.getCreditPacks).mockResolvedValue([
      { price_id: 'price_p10', credits: 1000, usd: 10 },
      { price_id: 'price_p50', credits: 5000, usd: 50 }
    ])
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Buy credits')).toBeInTheDocument())
    expect(screen.getByText('$10')).toBeInTheDocument()
    expect(screen.getByText('$50')).toBeInTheDocument()
  })
}
