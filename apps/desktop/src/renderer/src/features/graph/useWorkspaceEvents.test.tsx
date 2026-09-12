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
it('validates on every ready, invalidates only on graph.changed, and aborts on unmount', async () => {
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
  // The reconnect's `ready` is a validation, never a page walk.
  expect(ready).toHaveBeenCalledTimes(2)
  expect(changed).toHaveBeenCalledTimes(2)
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
it('routes a device frame to onDevices only — never to the graph catch-all', async () => {
  const devices = [
    {
      transport: 'usb_serial',
      device_ref: 'usb_serial:AB12',
      identity: null,
      level: 'board' as const,
      board: null,
      board_class: null,
      mcu_known: true,
      confidence: 0.5,
      evidence: [],
      ambiguous: false,
      last_seen_path: null
    }
  ]
  vi.mocked(streamProjectEvents).mockImplementation(async function* () {
    yield 'ready'
    yield { type: 'hardware.devices_changed', devices }
    yield { type: 'hardware.devices_changed', devices: [] }
  })
  const changed = vi.fn()
  const ready = vi.fn()
  const onDevices = vi.fn()
  renderHook(() => useWorkspaceEvents('p1', changed, ready, onDevices))
  await act(async () => {})
  expect(ready).toHaveBeenCalledOnce()
  expect(changed).not.toHaveBeenCalled()
  expect(onDevices).toHaveBeenNthCalledWith(1, devices)
  expect(onDevices).toHaveBeenNthCalledWith(2, [])
})
