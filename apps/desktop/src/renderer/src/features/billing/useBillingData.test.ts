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
  billingSnapshotTests()
  billingActionsTests()
})

// --- in-app checkout window (SOLUSDEV-114) -----------------------------------

const openCheckout = vi.fn()

function installCheckoutBridge(): void {
  ;(window as unknown as { solus?: unknown }).solus = {
    billing: { openExternal, openCheckout }
  }
}

describe('useBillingData with the in-app checkout bridge', () => {
  beforeEach(() => {
    openCheckout.mockReset()
    installCheckoutBridge()
    vi.mocked(resources.createSubscriptionCheckout).mockResolvedValue({ url: 'https://checkout/x' })
    vi.mocked(resources.createBillingPortal).mockResolvedValue({ url: 'https://portal/x' })
  })
  checkoutBridgeSuccessTests()
  checkoutWebhookRefreshTests()
  checkoutBridgeOutcomesTests()
})

function billingSnapshotTests(): void {
  it('loads subscription, credits, and packs when authenticated', async () => {
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.subscription?.plan).toBe('basic')
    expect(result.current.credits).toBe(1000)
    expect(result.current.packs).toEqual([{ price_id: 'price_p10', credits: 1000 }])
  })

  it('preserves the real balance and clears the development flag on refresh', async () => {
    vi.mocked(resources.getCredits).mockResolvedValue({
      user_id: 'u1',
      balance: 17,
      unlimited: true
    })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.credits).toBe(17)
    expect(result.current.unlimited).toBe(true)
    vi.mocked(resources.getCredits).mockResolvedValue({
      user_id: 'u1',
      balance: 12,
      unlimited: false
    })
    await act(() => result.current.refresh())
    expect(result.current.credits).toBe(12)
    expect(result.current.unlimited).toBe(false)
  })

  it('does not retain an unlimited claim when its refresh fails', async () => {
    vi.mocked(resources.getCredits).mockResolvedValue({
      user_id: 'u1',
      balance: 17,
      unlimited: true
    })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.getCredits).mockRejectedValue(new Error('offline'))
    await act(() => result.current.refresh())
    expect(result.current.unlimited).toBe(false)
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
}

function billingActionsTests(): void {
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
}

function checkoutBridgeSuccessTests(): void {
  it('prefers the in-app window over the system browser', async () => {
    openCheckout.mockResolvedValue({ status: 'success' })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.startCheckout('pro', 'month')
    })
    expect(openCheckout).toHaveBeenCalledWith('https://checkout/x')
    expect(openExternal).not.toHaveBeenCalled()
  })

  it('on success: refetches, shows a confirmation, and pings the notifications bell', async () => {
    openCheckout.mockResolvedValue({ status: 'success' })
    const bellRefresh = vi.fn()
    window.addEventListener('solus:notifications-refresh', bellRefresh)
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    const callsBefore = vi.mocked(resources.getSubscription).mock.calls.length
    await act(async () => {
      await result.current.startCheckout('pro', 'month')
    })
    await waitFor(() =>
      expect(vi.mocked(resources.getSubscription).mock.calls.length).toBeGreaterThan(callsBefore)
    )
    expect(result.current.notice).toMatch(/payment received/i)
    expect(bellRefresh).toHaveBeenCalled()
    window.removeEventListener('solus:notifications-refresh', bellRefresh)
  })
}

function checkoutWebhookRefreshTests(): void {
  it('schedules follow-up refetches to absorb webhook lag', async () => {
    openCheckout.mockResolvedValue({ status: 'success' })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.useFakeTimers()
    try {
      await act(async () => {
        await result.current.startCheckout('pro', 'month')
      })
      const callsAfterImmediate = vi.mocked(resources.getSubscription).mock.calls.length
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000)
      })
      expect(vi.mocked(resources.getSubscription).mock.calls.length).toBeGreaterThan(
        callsAfterImmediate
      )
    } finally {
      vi.useRealTimers()
    }
  })
}

function checkoutBridgeOutcomesTests(): void {
  it('on cancel or a dismissed window: canceled notice, nothing charged-looking', async () => {
    for (const status of ['cancel', 'closed'] as const) {
      openCheckout.mockResolvedValue({ status })
      const { result } = renderHook(() => useBillingData())
      await waitFor(() => expect(result.current.status).toBe('ready'))
      await act(async () => {
        await result.current.startCheckout('pro', 'month')
      })
      expect(result.current.notice).toMatch(/canceled/i)
      expect(result.current.notice).toMatch(/charged/i)
    }
  })

  it('portal return refetches without a notice', async () => {
    openCheckout.mockResolvedValue({ status: 'return' })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    const callsBefore = vi.mocked(resources.getSubscription).mock.calls.length
    await act(async () => {
      await result.current.openPortal()
    })
    await waitFor(() =>
      expect(vi.mocked(resources.getSubscription).mock.calls.length).toBeGreaterThan(callsBefore)
    )
    expect(result.current.notice).toBeNull()
  })

  it('busy (a checkout window is already open) surfaces a clear notice', async () => {
    openCheckout.mockResolvedValue({ status: 'busy' })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.startCheckout('pro', 'month')
    })
    expect(result.current.notice).toMatch(/already open/i)
  })

  it('a blocked URL surfaces the generic error notice', async () => {
    openCheckout.mockResolvedValue({ status: 'blocked' })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.startCheckout('pro', 'month')
    })
    expect(result.current.notice).toMatch(/went wrong/i)
  })
}
