// Billing data hook: subscription load, offline fallback, plan change.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useBillingData } from './useBillingData'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getSubscription: vi.fn(), updateSubscription: vi.fn() }
})

const SUB: resources.Subscription = {
  user_id: 'u1',
  plan: 'basic',
  status: 'trialing',
  limits: { max_projects: 3, max_teams: 2, max_integrations: 4 },
  expires_at: '2026-08-01T00:00:00Z',
  seat_count: 1
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.com' } })
  vi.mocked(resources.getSubscription).mockResolvedValue(SUB)
})

describe('useBillingData', () => {
  it('loads the subscription when authenticated', async () => {
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.subscription?.plan).toBe('basic')
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

  it('changePlan patches the plan and updates the subscription', async () => {
    vi.mocked(resources.updateSubscription).mockResolvedValue({ ...SUB, plan: 'pro' })
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.changePlan('pro')).toBe(true)
    })
    expect(vi.mocked(resources.updateSubscription)).toHaveBeenCalledWith('pro')
    expect(result.current.subscription?.plan).toBe('pro')
  })

  it('changePlan returns false and keeps the old plan on failure', async () => {
    vi.mocked(resources.updateSubscription).mockRejectedValue(new Error('403'))
    const { result } = renderHook(() => useBillingData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.changePlan('pro')).toBe(false)
    })
    expect(result.current.subscription?.plan).toBe('basic')
  })
})
