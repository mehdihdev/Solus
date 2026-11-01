// SOLUSDEV-319 — the bench view refetches on `ready` and on a newer `bench.view_changed`.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { streamProjectEvents } from '../../../lib/api/projectEvents'
import { useAuthStore } from '../../../store/authStore'
import { useBenchViewStore } from './useBenchView'
import { useBenchViewEvents } from './useBenchViewEvents'

vi.mock('../../../lib/api/projectEvents', () => ({ streamProjectEvents: vi.fn() }))

const noteReady = vi.fn(async () => undefined)
const noteHint = vi.fn(async () => undefined)
const original = useBenchViewStore.getState()

beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ status: 'authenticated', accessToken: 'test-session' })
  useBenchViewStore.setState({ noteReady, noteHint })
})
afterEach(() => {
  useBenchViewStore.setState({ noteReady: original.noteReady, noteHint: original.noteHint })
})

it('routes ready and bench.view_changed to the store and ignores other frames', async () => {
  vi.mocked(streamProjectEvents).mockImplementation(async function* () {
    yield 'ready'
    yield 'graph.changed'
    yield { type: 'layout.changed', version: 2 }
    yield { type: 'bench.view_changed', version: 9 }
  })
  const view = renderHook(() => useBenchViewEvents('p1'))
  await act(async () => {})
  expect(noteReady).toHaveBeenCalledWith('p1')
  expect(noteHint).toHaveBeenCalledTimes(1)
  expect(noteHint).toHaveBeenCalledWith('p1', 9)
  const signal = vi.mocked(streamProjectEvents).mock.calls[0]?.[0].signal
  view.unmount()
  expect(signal?.aborted).toBe(true)
})

it('opens nothing without a project or a token', async () => {
  useAuthStore.setState({ accessToken: null })
  renderHook(() => useBenchViewEvents('p1'))
  renderHook(() => useBenchViewEvents(null))
  await act(async () => {})
  expect(streamProjectEvents).not.toHaveBeenCalled()
})
