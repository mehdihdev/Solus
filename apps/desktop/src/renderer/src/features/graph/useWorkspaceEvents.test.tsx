import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { streamProjectEvents, type ProjectEvent } from '../../lib/api/projectEvents'
import { ApiError } from '../../lib/api/envelope.types'
import { useAuthStore } from '../../store/authStore'
import {
  LIVE_COALESCE_MS,
  liveKeys,
  resetLiveRevisions,
  useLiveRevisionStore
} from '../../store/liveRevisionStore'
import { LiveStreamHttpError } from '../../lib/api/liveStream'
import { useWorkspaceEvents } from './useWorkspaceEvents'
vi.mock('../../lib/api/projectEvents', () => ({ streamProjectEvents: vi.fn() }))
beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  resetLiveRevisions()
  vi.spyOn(Math, 'random').mockReturnValue(0.99)
  useAuthStore.setState({ status: 'authenticated', accessToken: 'test-session' })
})
afterEach(() => {
  vi.mocked(Math.random).mockRestore()
  resetLiveRevisions()
  vi.useRealTimers()
})
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
  await act(() => vi.advanceTimersByTimeAsync(1_000))
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

const noop = vi.fn()
const revisions = (): Readonly<Record<string, number>> => useLiveRevisionStore.getState().revisions
const flush = async (): Promise<void> => {
  await act(() => vi.advanceTimersByTimeAsync(LIVE_COALESCE_MS))
}

it('maps project frames to live revisions and records the layout version', async () => {
  vi.mocked(streamProjectEvents).mockImplementation(async function* () {
    yield 'ready'
    yield { type: 'layout.changed', version: 7 }
    yield { type: 'sources.changed' }
    yield { type: 'project.updated' }
    yield { type: 'job.updated', jobId: 'j', status: 'running' as const }
    await new Promise(() => undefined)
  })
  const changed = vi.fn()
  renderHook(() => useWorkspaceEvents('p1', changed))
  await act(async () => {})
  await flush()
  expect(revisions()).toEqual({
    [liveKeys.projectLayout('p1')]: 1,
    [liveKeys.projectSources('p1')]: 1,
    [liveKeys.projectDetail('p1')]: 1,
    [liveKeys.projectJobs('p1')]: 1
  })
  expect(useLiveRevisionStore.getState().layoutVersions).toEqual({ p1: 7 })
  expect(changed).not.toHaveBeenCalled()
})

const BANNER = 'Live updates unavailable. Check project access.'
/** A first connection that is revoked, then whatever `after` does on reconnect. */
function revokeThen(after: () => AsyncGenerator<ProjectEvent>): void {
  let call = 0
  vi.mocked(streamProjectEvents).mockImplementation(async function* () {
    call += 1
    if (call > 1) return yield* after()
    yield 'ready'
    yield { type: 'access.revoked' }
    await new Promise(() => undefined)
  })
}

it('reconnects once right away on access.revoked and continues without a banner when it succeeds', async () => {
  const ready = vi.fn()
  const changed = vi.fn()
  revokeThen(async function* () {
    yield 'ready'
    yield 'graph.changed'
    await new Promise(() => undefined)
  })
  const view = renderHook(() => useWorkspaceEvents('p1', changed, ready))
  await act(async () => {})
  expect(streamProjectEvents).toHaveBeenCalledTimes(2)
  expect(ready).toHaveBeenCalledTimes(2)
  expect(changed).toHaveBeenCalledTimes(1)
  expect(view.result.current).toBeNull()
  await act(() => vi.advanceTimersByTimeAsync(60_000))
  expect(streamProjectEvents).toHaveBeenCalledTimes(2)
})

it('shows the unavailable state and stops when the verify reconnect is refused with 403', async () => {
  revokeThen(async function* () {
    throw new LiveStreamHttpError(403)
    yield 'ready'
  })
  const view = renderHook(() => useWorkspaceEvents('p1', noop))
  await act(async () => {})
  await act(() => vi.advanceTimersByTimeAsync(120_000))
  expect(streamProjectEvents).toHaveBeenCalledTimes(2)
  expect(view.result.current).toBe(BANNER)
})

it('shows no banner when the verify reconnect gets 401, and resumes on a token change', async () => {
  revokeThen(async function* () {
    throw new LiveStreamHttpError(401)
    yield 'ready'
  })
  const view = renderHook(() => useWorkspaceEvents('p1', noop))
  await act(async () => {})
  await act(() => vi.advanceTimersByTimeAsync(120_000))
  expect(streamProjectEvents).toHaveBeenCalledTimes(2)
  expect(view.result.current).toBeNull()
  act(() => useAuthStore.setState({ accessToken: 'refreshed' }))
  await act(async () => {})
  expect(streamProjectEvents).toHaveBeenCalledTimes(3)
})

it('reads the token at connect time, not the one captured when the effect ran', async () => {
  revokeThen(async function* () {
    await new Promise(() => undefined)
    yield 'ready'
  })
  renderHook(() => useWorkspaceEvents('p1', noop))
  await act(async () => {})
  const getToken = vi.mocked(streamProjectEvents).mock.calls[0]?.[0].getToken
  useAuthStore.setState({ accessToken: 'fresh-token' })
  expect(await getToken?.()).toBe('fresh-token')
})

it('does not loop: a second revoke right after the verify reconnect falls back to backoff', async () => {
  vi.mocked(streamProjectEvents).mockImplementation(async function* () {
    yield 'ready'
    yield { type: 'access.revoked' }
  })
  renderHook(() => useWorkspaceEvents('p1', noop))
  await act(async () => {})
  // One immediate verify, then the stream ends and normal backoff applies.
  expect(streamProjectEvents).toHaveBeenCalledTimes(2)
  await act(() => vi.advanceTimersByTimeAsync(500))
  expect(vi.mocked(streamProjectEvents).mock.calls.length).toBeLessThanOrEqual(3)
})

it('backs off with jitter after a dropped stream and shows the reconnecting state', async () => {
  vi.mocked(streamProjectEvents).mockImplementation(async function* () {
    throw new LiveStreamHttpError(503)
    yield 'ready'
  })
  const view = renderHook(() => useWorkspaceEvents('p1', noop))
  await act(async () => {})
  expect(view.result.current).toBe('Live updates disconnected. Reconnecting…')
  await act(() => vi.advanceTimersByTimeAsync(989))
  expect(streamProjectEvents).toHaveBeenCalledTimes(1)
  await act(() => vi.advanceTimersByTimeAsync(1))
  expect(streamProjectEvents).toHaveBeenCalledTimes(2)
  // Second failure: ceiling doubles (2 s * 0.99), not a fixed 5 s retry.
  await act(() => vi.advanceTimersByTimeAsync(1_979))
  expect(streamProjectEvents).toHaveBeenCalledTimes(2)
  await act(() => vi.advanceTimersByTimeAsync(1))
  expect(streamProjectEvents).toHaveBeenCalledTimes(3)
})

it('stops permanently on 401 and 404, and on 401 resumes after a token change', async () => {
  for (const status of [401, 404]) {
    vi.mocked(streamProjectEvents).mockClear()
    vi.mocked(streamProjectEvents).mockImplementation(async function* () {
      throw new LiveStreamHttpError(status)
      yield 'ready'
    })
    const view = renderHook(() => useWorkspaceEvents('p1', noop))
    await act(async () => {})
    await act(() => vi.advanceTimersByTimeAsync(120_000))
    expect(streamProjectEvents).toHaveBeenCalledTimes(1)
    expect(view.result.current).toBe('Live updates unavailable. Check project access.')
    if (status === 401) {
      act(() => useAuthStore.setState({ accessToken: 'refreshed' }))
      await act(async () => {})
      expect(streamProjectEvents).toHaveBeenCalledTimes(2)
    }
    view.unmount()
  }
})
