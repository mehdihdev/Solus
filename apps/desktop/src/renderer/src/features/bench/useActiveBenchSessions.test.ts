// SOLUSDEV-72 — active-session poll behind the Bench screen's device-keyed
// view. Same honesty contract as useBridgeStatus: gated, projectId-keyed,
// null when unknown — never stale or fabricated.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useActiveBenchSessions, ACTIVE_SESSIONS_POLL_MS } from './useActiveBenchSessions'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, listBenchSessions: vi.fn() }
})

const mockedSessions = vi.mocked(resources.listBenchSessions)

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  mockedSessions.mockResolvedValue([])
})

describe('useActiveBenchSessions', () => {
  it('never fetches while gated or disabled', () => {
    vi.useFakeTimers()
    try {
      const gated = renderHook(() => useActiveBenchSessions('p1', true))
      gated.unmount()
      useWorkspaceStore.setState({ linked: true })
      renderHook(() => useActiveBenchSessions('p1', false))
      vi.advanceTimersByTime(ACTIVE_SESSIONS_POLL_MS * 2)
      expect(mockedSessions).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('polls active sessions and returns them', async () => {
    vi.useFakeTimers()
    try {
      useWorkspaceStore.setState({ linked: true })
      const { result } = renderHook(() => useActiveBenchSessions('p1', true))
      expect(mockedSessions).toHaveBeenCalledWith('p1')
      await act(() => vi.advanceTimersByTimeAsync(ACTIVE_SESSIONS_POLL_MS))
      expect(mockedSessions).toHaveBeenCalledTimes(2)
      expect(result.current).toEqual([])
    } finally {
      vi.useRealTimers()
    }
  })

  it('degrades to null (unknown) when the API is unreachable', async () => {
    vi.useFakeTimers()
    try {
      useWorkspaceStore.setState({ linked: true })
      mockedSessions.mockRejectedValue(new Error('unreachable'))
      const { result } = renderHook(() => useActiveBenchSessions('p1', true))
      await act(() => vi.advanceTimersByTimeAsync(0))
      expect(result.current).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})

it('discards a previous account response after switching accounts within one project', async () => {
  useWorkspaceStore.setState({ linked: true })
  useAuthStore.setState({ user: { email: 'first@example.test' }, status: 'authenticated' })
  let first!: (value: resources.BenchSession[]) => void
  mockedSessions.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        first = resolve
      })
  )
  const { result } = renderHook(() => useActiveBenchSessions('p1', true))
  await act(async () => {
    useAuthStore.setState({ user: { email: 'second@example.test' } })
  })
  await act(async () => {
    first([{ id: 'old-account' } as resources.BenchSession])
  })
  expect(result.current).toEqual([])
})

it('accepts a slow response without starting overlapping polls', async () => {
  vi.useFakeTimers()
  try {
    useWorkspaceStore.setState({ linked: true })
    let first!: (value: resources.BenchSession[]) => void
    mockedSessions.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          first = resolve
        })
    )
    const { result } = renderHook(() => useActiveBenchSessions('p1', true))
    await act(() => vi.advanceTimersByTimeAsync(ACTIVE_SESSIONS_POLL_MS * 3))
    expect(mockedSessions).toHaveBeenCalledTimes(1)
    await act(async () => {
      first([{ id: 'old-request' } as resources.BenchSession])
    })
    expect(result.current).toEqual([{ id: 'old-request' }])
  } finally {
    vi.useRealTimers()
  }
})

it.each(['account', 'project'])('discards a batched %s A→B→A response', async (boundary) => {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'A' } })
  useAuthStore.setState({ user: { email: 'a@example.test' }, status: 'authenticated' })
  let finish!: (value: resources.BenchSession[]) => void
  mockedSessions.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const { result } = renderHook(() => useActiveBenchSessions('p1', true))
  await act(async () => {
    if (boundary === 'account') {
      useAuthStore.setState({ user: { email: 'b@example.test' } })
      useAuthStore.setState({ user: { email: 'a@example.test' } })
    } else {
      useWorkspaceStore.setState({ project: { id: 'p2', name: 'B' } })
      useWorkspaceStore.setState({ project: { id: 'p1', name: 'A' } })
    }
    finish([{ id: 'expired' } as resources.BenchSession])
  })
  expect(result.current).toEqual([])
})
