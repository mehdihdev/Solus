import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useExternalBenchDevices } from './useExternalBenchDevices'

const state = vi.hoisted(() => ({
  request: vi.fn(),
  generation: 0,
  identity: 'alice',
  online: true
}))
vi.mock('../../lib/api/client', () => ({ api: { request: state.request } }))
vi.mock('../../store/authStore', () => ({
  useAuthStore: (select: (value: unknown) => unknown) =>
    select({ status: 'authenticated', user: { email: state.identity } })
}))
vi.mock('../graph/workspaceSession', () => ({
  useWorkspaceSessionGeneration: () => state.generation,
  workspaceSessionGeneration: () => state.generation
}))
vi.mock('../workspace/workspaceOnline', () => ({ useWorkspaceFetchEnabled: () => state.online }))

function deferred(): { promise: Promise<unknown>; resolve: (value: unknown) => void } {
  let resolve!: (value: unknown) => void
  return {
    promise: new Promise((done) => {
      resolve = done
    }),
    resolve: (value) => resolve(value)
  }
}

describe('external bench discovery', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    state.request.mockReset()
    state.generation = 0
    state.identity = 'alice'
    state.online = true
  })
  afterEach(() => vi.useRealTimers())

  it('polls without overlapping and deduplicates IDs', async () => {
    const pending = deferred()
    state.request.mockReturnValue(pending.promise)
    const { result, unmount } = renderHook(() => useExternalBenchDevices('project', true))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000)
    })
    expect(state.request).toHaveBeenCalledTimes(1)
    await act(async () => {
      pending.resolve({ device_ids: ['leader', 'leader', 'follower'] })
    })
    expect(result.current).toEqual(['follower', 'leader'])
    expect(state.request).toHaveBeenCalledWith('/projects/project/bench/telemetry-devices', {
      signal: expect.any(AbortSignal)
    })
    unmount()
  })

  it.each(['project', 'account', 'generation'])('discards stale %s results', async (change) => {
    const pending = deferred()
    state.request.mockReturnValueOnce(pending.promise).mockResolvedValue({ device_ids: ['new'] })
    const { result, rerender } = renderHook(
      ({ project }) => useExternalBenchDevices(project, true),
      { initialProps: { project: 'first' } }
    )
    if (change === 'account') state.identity = 'bob'
    if (change === 'generation') state.generation++
    rerender({ project: change === 'project' ? 'second' : 'first' })
    expect(result.current).toEqual([])
    await act(async () => {
      pending.resolve({ device_ids: ['old'] })
    })
    expect(result.current).toEqual(['new'])
  })

  it('retains failed discovery but clears offline scope', async () => {
    state.request
      .mockResolvedValueOnce({ device_ids: ['leader'] })
      .mockRejectedValue(new Error('offline'))
    const { result, rerender } = renderHook(() => useExternalBenchDevices('project', true))
    await act(async () => {})
    expect(result.current).toEqual(['leader'])
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(result.current).toEqual(['leader'])
    state.online = false
    rerender()
    expect(result.current).toEqual([])
  })
})
