import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import * as api from '../../lib/api/resources.hosted'
import { useAuthStore } from '../../store/authStore'
import { useAccountHosted } from './useAccountHosted'
vi.mock('../../lib/api/resources.hosted', () => ({
  getAccountHosted: vi.fn(),
  probeAccountHosted: vi.fn()
}))
vi.mock('../../lib/desktopBridge', () => ({
  getDesktopHostedBridge: () => ({ openStore: async () => ({ ok: true }) }),
  getDesktopOAuthBridge: () => null
}))
const hosted = {
  server: 'fs',
  display_name: 'FeatureScript',
  notice: '',
  subscribe_url: 'https://example.test'
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
  useAuthStore.setState({ accessToken: 'session-one' })
  vi.mocked(api.getAccountHosted).mockResolvedValue({
    server: 'fs',
    state: 'subscription_required',
    tool_count: 0
  })
})
afterEach(() => vi.useRealTimers())
it('bounds automatic checks even when non-ready provider states alternate', async () => {
  let calls = 0
  vi.mocked(api.probeAccountHosted).mockImplementation(async () => ({
    server: 'fs',
    state: ++calls % 2 ? 'not_enabled' : 'subscription_required',
    tool_count: 0
  }))
  const { result } = renderHook(() => useAccountHosted('c1', hosted))
  await act(async () => {})
  await act(async () => result.current.openStore())
  for (let i = 0; i < 15; i++) await act(async () => vi.advanceTimersByTimeAsync(5000))
  expect(calls).toBeGreaterThan(0)
  expect(calls).toBeLessThanOrEqual(12)
  expect(result.current.monitoring).toBe(false)
})
it('discards late status and stops polling on signout', async () => {
  let finish!: (value: Awaited<ReturnType<typeof api.probeAccountHosted>>) => void
  vi.mocked(api.probeAccountHosted).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const { result } = renderHook(() => useAccountHosted('c1', hosted))
  await act(async () => {})
  await act(async () => result.current.openStore())
  await act(async () => vi.advanceTimersByTimeAsync(5000))
  act(() => useAuthStore.setState({ accessToken: null }))
  await act(async () => finish({ server: 'fs', state: 'ready', tool_count: 1 }))
  await act(async () => vi.advanceTimersByTimeAsync(60000))
  expect(result.current.status).toBeNull()
  expect(api.probeAccountHosted).toHaveBeenCalledTimes(1)
})

it('stops at the elapsed deadline even if a probe never settles', async () => {
  vi.mocked(api.probeAccountHosted).mockImplementation(() => new Promise(() => {}))
  const { result } = renderHook(() => useAccountHosted('c1', hosted))
  await act(async () => {})
  await act(async () => result.current.openStore())
  await act(async () => vi.advanceTimersByTimeAsync(61000))
  expect(result.current.monitoring).toBe(false)
})
