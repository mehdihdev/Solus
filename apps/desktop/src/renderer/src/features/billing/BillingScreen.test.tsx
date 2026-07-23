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
  it('shows the current plan, status, and credits', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Billing')).toBeInTheDocument())
    expect(screen.getByText('Basic')).toBeInTheDocument()
    expect(screen.getByText('TRIAL')).toBeInTheDocument()
    expect(screen.getByText('1,000')).toBeInTheDocument() // credit balance
  })

  it('shows an honest offline notice when signed out', async () => {
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    render(<BillingScreen />)
    await waitFor(() =>
      expect(screen.getByText(/Sign in to Solus to manage billing/)).toBeInTheDocument()
    )
  })

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

  it('marks the active plan as current (not subscribable)', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    // Only the Pro card offers Subscribe; Basic (current) shows CURRENT PLAN.
    expect(screen.getAllByRole('button', { name: /Subscribe/i })).toHaveLength(1)
  })
})
