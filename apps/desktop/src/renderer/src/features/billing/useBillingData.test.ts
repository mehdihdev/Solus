// Billing data hook: subscription + credits + packs load, offline fallback, and
// the real Stripe actions (checkout / pack / portal open a URL via the bridge).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useBillingData } from './useBillingData'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { ApiError } from '../../lib/api/envelope.types'
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
  vi.mocked(resources.getCreditPacks).mockResolvedValue([{ price_id: 'price_p10', credits: 1000 }])
  ;(window as unknown as { solus?: unknown }).solus = { billing: { openExternal } }
})

afterEach(() => {
  delete (window as unknown as { solus?: unknown }).solus
})

describe('useBillingData', () => {
  it('loads subscription, credits, and packs when authenticated', async () => {
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.subscription?.plan).toBe('basic')
    expect(result.current.credits).toBe(1000)
    expect(result.current.packs).toEqual([{ price_id: 'price_p10', credits: 1000 }])
  })

  it('is offline when neither authenticated nor linked', async () => {
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(resources.getSubscription).not.toHaveBeenCalled()
  })

  it('treats a 404 (no subscription) as ready with a null plan', async () => {
    vi.mocked(resources.getSubscription).mockRejectedValue(new Error('404'))
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.subscription).toBeNull()
  })

  it('startCheckout opens the Stripe URL for the chosen plan + interval', async () => {
    vi.mocked(resources.createSubscriptionCheckout).mockResolvedValue({ url: 'https://checkout/x' })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.startCheckout('pro', 'year')
    })
    expect(resources.createSubscriptionCheckout).toHaveBeenCalledWith('pro', 'year')
    expect(openExternal).toHaveBeenCalledWith('https://checkout/x')
  })

  it('buyPack opens the Stripe URL for the pack', async () => {
    vi.mocked(resources.createPackCheckout).mockResolvedValue({ url: 'https://checkout/pack' })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.buyPack('price_p10')
    })
    expect(resources.createPackCheckout).toHaveBeenCalledWith('price_p10')
    expect(openExternal).toHaveBeenCalledWith('https://checkout/pack')
  })

  it('openPortal opens the billing-portal URL', async () => {
    vi.mocked(resources.createBillingPortal).mockResolvedValue({ url: 'https://portal/x' })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.openPortal()
    })
    expect(openExternal).toHaveBeenCalledWith('https://portal/x')
  })

  it('surfaces a notice (and opens nothing) when billing is unconfigured', async () => {
    vi.mocked(resources.createSubscriptionCheckout).mockRejectedValue(
      new ApiError(503, 'billing_unconfigured', 'nope')
    )
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.startCheckout('pro', 'month')
    })
    expect(openExternal).not.toHaveBeenCalled()
    expect(result.current.notice).toMatch(/configured/i)
  })
})
