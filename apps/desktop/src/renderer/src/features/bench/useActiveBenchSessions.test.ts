// SOLUSDEV-72 — active-session poll behind the Bench screen's device-keyed
// view. Same honesty contract as useBridgeStatus: gated, projectId-keyed,
// null when unknown — never stale or fabricated.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useActiveBenchSessions, ACTIVE_SESSIONS_POLL_MS } from './useActiveBenchSessions'
import { useWorkspaceStore } from '../../store/workspaceStore'
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
      expect(mockedSessions).toHaveBeenCalledWith('p1', { status: 'active' })
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
