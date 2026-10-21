// Billing screen: wireflow states (docs/wireflows/billing.md), Stripe flows,
// interval toggle, credit packs, banners, and the offline notice.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BillingScreen } from './BillingScreen'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { ApiError } from '../../lib/api/envelope.types'
import * as resources from '../../lib/api/resources'
import * as billing from '../../lib/api/resources.billing'
import { PRICES, SUMMARY } from './billingTestFixtures'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getCredits: vi.fn(),
    getCreditPacks: vi.fn(),
    createSubscriptionCheckout: vi.fn(),
    createPackCheckout: vi.fn()
  }
})

vi.mock('../../lib/api/resources.billing', () => ({
  getBillingSubscription: vi.fn(),
  getBillingSummary: vi.fn(),
  createBillingPortalFlow: vi.fn()
}))

const FUTURE = '2099-01-01T00:00:00Z'

const TRIAL_SUB: billing.BillingSubscription = {
  user_id: 'u1',
  plan: 'basic',
  status: 'trialing',
  limits: { max_projects: 3, max_teams: 2, max_integrations: 4 },
  expires_at: FUTURE,
  seat_count: 1,
  stripe_subscription_id: null,
  billing_interval: null,
  current_period_end: null,
  trial_expired: false
}

const LIVE: billing.BillingSubscription = {
  ...TRIAL_SUB,
  status: 'active',
  expires_at: null,
  stripe_subscription_id: 'sub_live',
  billing_interval: 'month',
  current_period_end: '2026-11-19T00:00:00Z'
}

const TRIAL_SUMMARY: billing.BillingSummary = {
  ...SUMMARY,
  status: 'trialing',
  billing_interval: null,
  current_period_end: null,
  trial: { state: 'active', ends_at: FUTURE },
  next_invoice: null,
  payment_method: null
}

const openExternal = vi.fn().mockResolvedValue({ ok: true })
const contactSales = vi.fn().mockResolvedValue({ ok: true })

function mockState(
  sub: billing.BillingSubscription | null,
  summary: billing.BillingSummary | null
): void {
  vi.mocked(billing.getBillingSubscription).mockImplementation(async () => {
    if (!sub) throw new Error('404')
    return sub
  })
  vi.mocked(billing.getBillingSummary).mockImplementation(async () => {
    if (!summary) throw new Error('summary down')
    return summary
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.com' } })
  mockState(TRIAL_SUB, TRIAL_SUMMARY)
  vi.mocked(resources.getCredits).mockResolvedValue({ user_id: 'u1', balance: 1000 })
  vi.mocked(resources.getCreditPacks).mockResolvedValue([{ price_id: 'price_p10', credits: 500 }])
  vi.mocked(resources.createSubscriptionCheckout).mockResolvedValue({ url: 'https://checkout/x' })
  vi.mocked(resources.createPackCheckout).mockResolvedValue({ url: 'https://checkout/pack' })
  vi.mocked(billing.createBillingPortalFlow).mockResolvedValue({ url: 'https://portal/x' })
  ;(window as unknown as { solus?: unknown }).solus = {
    billing: { openExternal, contactSales }
  }
})

afterEach(() => {
  delete (window as unknown as { solus?: unknown }).solus
})

async function ready(): Promise<void> {
  await screen.findByText('Buy credits')
}

function plan(name: string): HTMLElement {
  return screen.getByRole('group', { name })
}

describe('BillingScreen', () => {
  billingSummaryTests()
  billingCheckoutTests()
  billingPlanDetailsTests()
  billingBannerTests()
  billingCancellationAndPacksTests()
})

function billingSummaryTests(): void {
  it('shows a spinner while loading', () => {
    render(<BillingScreen />)
    expect(screen.getByTestId('billing-loading')).toBeInTheDocument()
  })

  it('shows the current plan, status, and credits', async () => {
    render(<BillingScreen />)
    await ready()
    expect(screen.getByText('Basic plan')).toBeInTheDocument()
    expect(screen.getByText('TRIALING')).toBeInTheDocument()
    expect(screen.getByText('1,000')).toBeInTheDocument()
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
    mockState(null, SUMMARY)
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
    expect(await screen.findByText(/Sign in to Solus to manage billing/)).toBeInTheDocument()
  })
}

function billingCheckoutTests(): void {
  it('opens Stripe Checkout for the chosen plan (monthly by default)', async () => {
    render(<BillingScreen />)
    await ready()
    await userEvent.click(within(plan('Pro')).getByRole('button', { name: /Subscribe/ }))
    await waitFor(() =>
      expect(resources.createSubscriptionCheckout).toHaveBeenCalledWith('pro', 'month')
    )
    expect(openExternal).toHaveBeenCalledWith('https://checkout/x')
  })

  it('honours the yearly interval toggle', async () => {
    render(<BillingScreen />)
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Yearly' }))
    await userEvent.click(within(plan('Pro')).getByRole('button', { name: /Subscribe/ }))
    await waitFor(() =>
      expect(resources.createSubscriptionCheckout).toHaveBeenCalledWith('pro', 'year')
    )
  })

  it('buys a credit pack via Stripe Checkout', async () => {
    render(<BillingScreen />)
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Buy' }))
    await waitFor(() => expect(resources.createPackCheckout).toHaveBeenCalledWith('price_p10'))
  })

  it('opens the general billing portal with no flow', async () => {
    render(<BillingScreen />)
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Manage billing' }))
    await waitFor(() => expect(billing.createBillingPortalFlow).toHaveBeenCalledWith(undefined))
    expect(openExternal).toHaveBeenCalledWith('https://portal/x')
  })

  it('routes a live Stripe subscriber to the portal update flow, never a second checkout', async () => {
    mockState(LIVE, SUMMARY)
    render(<BillingScreen />)
    await ready()
    expect(screen.queryByRole('button', { name: /Subscribe/ })).not.toBeInTheDocument()
    await userEvent.click(within(plan('Pro')).getByRole('button', { name: 'Change plan' }))
    await waitFor(() => expect(billing.createBillingPortalFlow).toHaveBeenCalledWith('update'))
    expect(resources.createSubscriptionCheckout).not.toHaveBeenCalled()
  })

  it('Cancel plan opens the cancel flow; an already-scheduled 409 shows the wireflow copy', async () => {
    mockState(LIVE, SUMMARY)
    vi.mocked(billing.createBillingPortalFlow).mockRejectedValue(
      new ApiError(409, 'cancel_already_scheduled', 'x')
    )
    render(<BillingScreen />)
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel plan' }))
    await waitFor(() => expect(billing.createBillingPortalFlow).toHaveBeenCalledWith('cancel'))
    expect(await screen.findByText('Your plan is already scheduled to end.')).toBeInTheDocument()
  })
}

function billingPlanDetailsTests(): void {
  it('marks the live plan+interval as current and nothing else', async () => {
    mockState(LIVE, SUMMARY)
    render(<BillingScreen />)
    await ready()
    expect(within(plan('Basic')).getByText('CURRENT PLAN')).toBeInTheDocument()
    expect(screen.getAllByText('CURRENT PLAN')).toHaveLength(1)
  })

  it('shows server prices for the selected interval (no hard-coded numbers)', async () => {
    mockState(TRIAL_SUB, {
      ...TRIAL_SUMMARY,
      prices: PRICES.map((p) => ({ ...p, amount_cents: p.amount_cents + 100 }))
    })
    render(<BillingScreen />)
    await ready()
    expect(screen.getByText('$26')).toBeInTheDocument()
    expect(screen.getByText('$36')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Yearly' }))
    expect(screen.getByText('$201')).toBeInTheDocument()
    expect(screen.queryByText('$26')).not.toBeInTheDocument()
  })

  it('lists the plan features including starting credits (ADR-024)', async () => {
    render(<BillingScreen />)
    await ready()
    expect(screen.getAllByText('All capabilities')).toHaveLength(2)
    expect(screen.getByText(/Starts with 2,500 credits/)).toBeInTheDocument()
    expect(screen.getByText(/Starts with 10,000 credits/)).toBeInTheDocument()
  })

  it('presents Enterprise as per-seat, org-paid, with a Contact sales button', async () => {
    render(<BillingScreen />)
    await ready()
    expect(screen.getByText(/Per-seat pricing/)).toBeInTheDocument()
    expect(screen.getByText(/organization('|’)s wallet/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Contact sales' }))
    expect(contactSales).toHaveBeenCalledTimes(1)
    expect(document.body.innerHTML).not.toContain('mailto:')
  })
}

function billingBannerTests(): void {
  it('warns (role=alert) when the local trial has ended', async () => {
    mockState(
      { ...TRIAL_SUB, expires_at: '2026-10-10T00:00:00Z', trial_expired: true },
      { ...TRIAL_SUMMARY, trial: { state: 'expired', ends_at: '2026-10-10T00:00:00Z' } }
    )
    render(<BillingScreen />)
    await ready()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Trial ended October 10, 2026 — choose a plan'
    )
    expect(within(plan('Pro')).getByRole('button', { name: /Subscribe/ })).toBeEnabled()
  })

  it('warns about a failed payment when past due', async () => {
    mockState({ ...LIVE, status: 'past_due' }, SUMMARY)
    render(<BillingScreen />)
    await ready()
    expect(screen.getByRole('alert')).toHaveTextContent(
      /Payment failed — update your payment method/
    )
  })

  it('warns when Stripe is unavailable and disables purchases but not Contact sales', async () => {
    mockState(LIVE, {
      ...SUMMARY,
      stripe_status: 'unavailable',
      prices: null,
      next_invoice: null,
      payment_method: null
    })
    render(<BillingScreen />)
    await ready()
    expect(screen.getByRole('alert')).toHaveTextContent(/Billing is temporarily unavailable/)
    expect(screen.getByRole('button', { name: 'Manage billing' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Buy' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Contact sales' })).toBeEnabled()
  })

  it('degrades to the unavailable state when the summary request fails, staying online', async () => {
    mockState(LIVE, null)
    render(<BillingScreen />)
    await ready()
    expect(screen.getByRole('alert')).toHaveTextContent(/temporarily unavailable/)
    expect(screen.getByText('Basic plan')).toBeInTheDocument()
  })

  it('informs (role=status) when billing is unconfigured', async () => {
    mockState(LIVE, { ...SUMMARY, stripe_status: 'unconfigured', prices: null })
    render(<BillingScreen />)
    await ready()
    expect(screen.getByRole('status')).toHaveTextContent(
      "Billing isn't configured for this environment."
    )
  })
}

function billingCancellationAndPacksTests(): void {
  it('shows a persistent end-date bar while a cancellation is pending', async () => {
    mockState(
      { ...LIVE, plan: 'pro', cancel_at: '2026-09-15T00:00:00Z' },
      { ...SUMMARY, plan: 'pro', cancel_at: '2026-09-15T00:00:00Z', next_invoice: null }
    )
    render(<BillingScreen />)
    await ready()
    const bar = screen.getByRole('status')
    expect(bar.textContent).toMatch(/Pro plan ends on/i)
    expect(bar.textContent).toMatch(/September 15, 2026/)
    expect(bar.textContent).toMatch(/keep full access until then/i)
  })

  it('shows no end-date bar without a pending cancellation or once canceled', async () => {
    render(<BillingScreen />)
    await ready()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows no end-date bar for a canceled subscription', async () => {
    mockState({ ...LIVE, status: 'canceled', cancel_at: null }, SUMMARY)
    render(<BillingScreen />)
    await ready()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByText('No active plan')).toBeInTheDocument()
  })

  it('shows the dollar price on credit packs when the server provides it', async () => {
    vi.mocked(resources.getCreditPacks).mockResolvedValue([
      { price_id: 'price_p10', credits: 1000, usd: 10 },
      { price_id: 'price_p50', credits: 5000, usd: 50 }
    ])
    render(<BillingScreen />)
    await ready()
    expect(screen.getByText('$10')).toBeInTheDocument()
    expect(screen.getByText('$50')).toBeInTheDocument()
  })

  it('never hides the packs section: explicit notice when packs are unavailable', async () => {
    mockState(TRIAL_SUB, { ...TRIAL_SUMMARY, packs_available: false })
    render(<BillingScreen />)
    await ready()
    expect(screen.getByText("Credit packs aren't available right now.")).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Buy' })).not.toBeInTheDocument()
  })

  it('shows the same notice when the pack list is empty', async () => {
    vi.mocked(resources.getCreditPacks).mockResolvedValue([])
    render(<BillingScreen />)
    await ready()
    expect(screen.getByText("Credit packs aren't available right now.")).toBeInTheDocument()
  })
}
