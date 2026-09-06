import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { streamProjectEvents } from '../../lib/api/projectEvents'
import { ApiError } from '../../lib/api/envelope.types'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceEvents } from './useWorkspaceEvents'
vi.mock('../../lib/api/projectEvents', () => ({ streamProjectEvents: vi.fn() }))
beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  useAuthStore.setState({ status: 'authenticated', accessToken: 'test-session' })
})
afterEach(() => vi.useRealTimers())
it('invalidates changes, catches up after reconnect, and aborts on unmount', async () => {
  vi.mocked(streamProjectEvents).mockImplementation(async function* () {
    yield 'ready'
    yield 'graph.changed'
  })
  const changed = vi.fn()
  const ready = vi.fn()
  const view = renderHook(() => useWorkspaceEvents('p1', changed, ready))
  await act(async () => {})
  expect(ready).toHaveBeenCalledOnce()
  expect(changed).toHaveBeenCalledTimes(1)
  expect(streamProjectEvents).toHaveBeenCalledTimes(1)
  await act(() => vi.advanceTimersByTimeAsync(5_000))
  expect(changed).toHaveBeenCalledTimes(3)
  const signal = vi.mocked(streamProjectEvents).mock.calls[1]?.[0].signal
  view.unmount()
  expect(signal?.aborted).toBe(true)
  await act(() => vi.advanceTimersByTimeAsync(10_000))
  expect(streamProjectEvents).toHaveBeenCalledTimes(2)
})
it('does not retry a permission denial', async () => {
  vi.mocked(streamProjectEvents).mockImplementation(async function* () {
    throw new ApiError(403, 'forbidden', 'No access')
    yield 'ready'
  })
  const changed = vi.fn()
  const view = renderHook(() => useWorkspaceEvents('p1', changed))
  await act(async () => {})
  await act(() => vi.advanceTimersByTimeAsync(30_000))
  expect(streamProjectEvents).toHaveBeenCalledTimes(1)
  expect(view.result.current).toBe('Live updates unavailable. Check project access.')
})
it('drops late frames when switching projects and opens only the new scope', async () => {
  let release: () => void = () => undefined
  vi.mocked(streamProjectEvents).mockImplementation(async function* (options) {
    if (options.projectId === 'p1')
      await new Promise<void>((resolve) => {
        release = resolve
      })
    yield 'graph.changed'
  })
  const changed = vi.fn()
  const view = renderHook(({ id }) => useWorkspaceEvents(id, changed), {
    initialProps: { id: 'p1' }
  })
  view.rerender({ id: 'p2' })
  await act(async () => {
    release()
  })
  expect(changed).toHaveBeenCalledTimes(1)
  expect(vi.mocked(streamProjectEvents).mock.calls[0]?.[0].signal?.aborted).toBe(true)
})
