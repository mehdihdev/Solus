// Billing data hook: subscription + credits + packs load, offline fallback, and
// the real Stripe actions (checkout / pack / portal open a URL via the bridge).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useBillingData } from './useBillingData'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { ApiError } from '../../lib/api/envelope.types'
import * as resources from '../../lib/api/resources'
import * as billing from '../../lib/api/resources.billing'

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

const SUB: billing.BillingSubscription = {
  user_id: 'u1',
  plan: 'basic',
  status: 'trialing',
  limits: { max_projects: 3, max_teams: 2, max_integrations: 4 },
  expires_at: '2026-08-01T00:00:00Z',
  seat_count: 1
}

const SUMMARY: billing.BillingSummary = {
  plan: 'basic',
  status: 'trialing',
  billing_interval: null,
  current_period_end: null,
  cancel_at: null,
  trial: { state: 'active', ends_at: '2026-08-01T00:00:00Z' },
  next_invoice: null,
  payment_method: null,
  prices: null,
  packs_available: true,
  stripe_status: 'ok'
}

const openExternal = vi.fn().mockResolvedValue({ ok: true })

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.com' } })
  vi.mocked(billing.getBillingSubscription).mockResolvedValue(SUB)
  vi.mocked(billing.getBillingSummary).mockResolvedValue(SUMMARY)
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
  billingSummaryTests()
  billingPortalFlowTests()
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
    vi.mocked(billing.createBillingPortalFlow).mockResolvedValue({ url: 'https://portal/x' })
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
    expect(billing.getBillingSubscription).not.toHaveBeenCalled()
  })

  it('treats a 404 (no subscription) as ready with a null plan', async () => {
    vi.mocked(billing.getBillingSubscription).mockRejectedValue(new Error('404'))
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
    vi.mocked(billing.createBillingPortalFlow).mockResolvedValue({ url: 'https://portal/x' })
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
    const callsBefore = vi.mocked(billing.getBillingSubscription).mock.calls.length
    await act(async () => {
      await result.current.startCheckout('pro', 'month')
    })
    await waitFor(() =>
      expect(vi.mocked(billing.getBillingSubscription).mock.calls.length).toBeGreaterThan(
        callsBefore
      )
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
      const callsAfterImmediate = vi.mocked(billing.getBillingSubscription).mock.calls.length
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000)
      })
      expect(vi.mocked(billing.getBillingSubscription).mock.calls.length).toBeGreaterThan(
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
    const callsBefore = vi.mocked(billing.getBillingSubscription).mock.calls.length
    await act(async () => {
      await result.current.openPortal()
    })
    await waitFor(() =>
      expect(vi.mocked(billing.getBillingSubscription).mock.calls.length).toBeGreaterThan(
        callsBefore
      )
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
    expect(result.current.notice).toMatch(/couldn.t open checkout/i)
  })
}

function billingSummaryTests(): void {
  it('exposes the summary alongside the other data', async () => {
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.summary).toEqual(SUMMARY)
  })

  it('a failing summary does not flip the page offline (summary is null = degraded)', async () => {
    vi.mocked(billing.getBillingSummary).mockRejectedValue(new ApiError(429, 'rate_limited', 'x'))
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.summary).toBeNull()
    expect(result.current.subscription?.plan).toBe('basic')
  })

  it('stamps the snapshot time used for read-time trial expiry', async () => {
    const before = Date.now()
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.asOf).toBeGreaterThanOrEqual(before)
  })

  it('refetches the summary on window focus', async () => {
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    const before = vi.mocked(billing.getBillingSummary).mock.calls.length
    act(() => {
      window.dispatchEvent(new Event('focus'))
    })
    await waitFor(() =>
      expect(vi.mocked(billing.getBillingSummary).mock.calls.length).toBeGreaterThan(before)
    )
  })
}

async function openFlow(
  flow: 'update' | 'cancel' | undefined
): Promise<ReturnType<typeof renderHook<ReturnType<typeof useBillingData>, unknown>>> {
  const hook = renderHook(() => useBillingData())
  await waitFor(() => expect(hook.result.current.status).toBe('ready'))
  await act(async () => {
    await hook.result.current.openPortalFlow(flow)
  })
  return hook
}

function billingPortalFlowTests(): void {
  it.each([undefined, 'update', 'cancel'] as const)(
    'openPortalFlow(%s) requests that flow and opens the URL',
    async (flow) => {
      vi.mocked(billing.createBillingPortalFlow).mockResolvedValue({ url: 'https://portal/f' })
      await openFlow(flow)
      expect(billing.createBillingPortalFlow).toHaveBeenCalledWith(flow)
      expect(openExternal).toHaveBeenCalledWith('https://portal/f')
    }
  )

  it('portal flows trigger the 1.5/4/10 s refetches (subscription and summary)', async () => {
    vi.mocked(billing.createBillingPortalFlow).mockResolvedValue({ url: 'https://portal/f' })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.useFakeTimers()
    try {
      await act(async () => {
        await result.current.openPortalFlow('update')
      })
      const subBefore = vi.mocked(billing.getBillingSubscription).mock.calls.length
      const sumBefore = vi.mocked(billing.getBillingSummary).mock.calls.length
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1600)
      })
      expect(vi.mocked(billing.getBillingSubscription).mock.calls.length).toBe(subBefore + 1)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000)
      })
      expect(vi.mocked(billing.getBillingSubscription).mock.calls.length).toBe(subBefore + 3)
      expect(vi.mocked(billing.getBillingSummary).mock.calls.length).toBe(sumBefore + 3)
    } finally {
      vi.useRealTimers()
    }
  })

  it.each([
    ['update', 'no_active_subscription', /can.t be changed right now — use Manage billing/],
    ['cancel', 'cancel_already_scheduled', /already scheduled to end/],
    [undefined, 'no_billing_customer', /Start a subscription first/]
  ] as const)('maps a 409 on flow %s (%s) to the wireflow copy', async (flow, code, copy) => {
    vi.mocked(billing.createBillingPortalFlow).mockRejectedValue(new ApiError(409, code, 'x'))
    const { result } = await openFlow(flow)
    expect(result.current.notice).toMatch(copy)
    expect(openExternal).not.toHaveBeenCalled()
  })

  it('cancel_already_scheduled also refetches so the page shows the pending cancel', async () => {
    vi.mocked(billing.createBillingPortalFlow).mockRejectedValue(
      new ApiError(409, 'cancel_already_scheduled', 'x')
    )
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    const before = vi.mocked(billing.getBillingSubscription).mock.calls.length
    await act(async () => {
      await result.current.openPortalFlow('cancel')
    })
    await waitFor(() =>
      expect(vi.mocked(billing.getBillingSubscription).mock.calls.length).toBeGreaterThan(before)
    )
  })

  it('a generic portal failure says it could not open billing', async () => {
    vi.mocked(billing.createBillingPortalFlow).mockRejectedValue(new Error('boom'))
    const { result } = await openFlow(undefined)
    expect(result.current.notice).toBe('Couldn’t open billing — try again.')
  })

  it('a 502/503 checkout failure uses the Stripe-unavailable copy', async () => {
    vi.mocked(resources.createSubscriptionCheckout).mockRejectedValue(
      new ApiError(502, 'billing_provider_error', 'x')
    )
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.startCheckout('pro', 'month')
    })
    expect(result.current.notice).toMatch(/temporarily unavailable/)
  })
}
