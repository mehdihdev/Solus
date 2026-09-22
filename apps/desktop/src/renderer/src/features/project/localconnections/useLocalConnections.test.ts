// SOLUSDEV-72 — polling hook for the Local Connections section. Cloned from
// the useBridgeStatus pattern: projectId-keyed result, ~5s poll while fetches
// are enabled, degrade to null on error — honest offline, never fabricated.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import {
  useLocalConnections,
  useLocalTools,
  LOCAL_CONNECTIONS_POLL_MS
} from './useLocalConnections'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import * as resources from '../../../lib/api/resources'
import type { BenchSources } from '../../../lib/api/resources'

vi.mock('../../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../lib/api/resources')>()
  return {
    ...actual,
    getBenchSources: vi.fn(),
    listBenchSessions: vi.fn(),
    listLocalTools: vi.fn()
  }
})

const SOURCES: BenchSources = {
  runner: { available: true, reason: null },
  simulators: [{ kind: 'mujoco', available: true, reason: null }],
  devices: []
}

const mockedSources = vi.mocked(resources.getBenchSources)
const mockedSessions = vi.mocked(resources.listBenchSessions)
const mockedTools = vi.mocked(resources.listLocalTools)

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  mockedSources.mockResolvedValue(SOURCES)
  mockedSessions.mockResolvedValue([])
})

describe('useLocalConnections', () => {
  localConnectionsPollingTests()
  localConnectionsIsolationTests()
})

describe('useLocalTools', () => {
  it('fetches once while enabled and returns the tool list', async () => {
    useWorkspaceStore.setState({ linked: true })
    mockedTools.mockResolvedValue([
      {
        type: 'fusion',
        display_name: 'Fusion',
        hosting: 'vendor-run',
        url_host: '127.0.0.1:27182',
        connect_notice: 'Launch Fusion',
        requires: 'companion'
      }
    ])
    const { result } = renderHook(() => useLocalTools())
    await act(async () => undefined)
    expect(mockedTools).toHaveBeenCalledTimes(1)
    expect(result.current?.[0].display_name).toBe('Fusion')
  })

  it('degrades to null when gated or unreachable', async () => {
    const { result } = renderHook(() => useLocalTools())
    expect(mockedTools).not.toHaveBeenCalled()
    expect(result.current).toBeNull()

    useWorkspaceStore.setState({ linked: true })
    mockedTools.mockRejectedValue(new Error('unreachable'))
    const { result: failed } = renderHook(() => useLocalTools())
    await act(async () => undefined)
    expect(failed.current).toBeNull()
  })
})

function localConnectionsPollingTests(): void {
  it('never fetches while workspace fetches are disabled', () => {
    vi.useFakeTimers()
    try {
      renderHook(() => useLocalConnections('p1'))
      vi.advanceTimersByTime(LOCAL_CONNECTIONS_POLL_MS * 3)
      expect(mockedSources).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('never fetches without a project id', () => {
    vi.useFakeTimers()
    try {
      useWorkspaceStore.setState({ linked: true })
      renderHook(() => useLocalConnections(null))
      vi.advanceTimersByTime(LOCAL_CONNECTIONS_POLL_MS * 3)
      expect(mockedSources).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('loads sources + active sessions immediately, then re-polls every 5 s', async () => {
    vi.useFakeTimers()
    try {
      useWorkspaceStore.setState({ linked: true })
      const { result } = renderHook(() => useLocalConnections('p1'))
      expect(mockedSources).toHaveBeenCalledWith('p1')
      expect(mockedSessions).toHaveBeenCalledWith('p1', { status: 'active' })
      await act(() => vi.advanceTimersByTimeAsync(LOCAL_CONNECTIONS_POLL_MS))
      expect(mockedSources).toHaveBeenCalledTimes(2)
      expect(result.current.data?.sources).toEqual(SOURCES)
      expect(result.current.data?.sessions).toEqual([])
    } finally {
      vi.useRealTimers()
    }
  })

  it('degrades to null when the API is unreachable — never stale data', async () => {
    vi.useFakeTimers()
    try {
      useWorkspaceStore.setState({ linked: true })
      mockedSources.mockRejectedValue(new Error('unreachable'))
      const { result } = renderHook(() => useLocalConnections('p1'))
      await act(() => vi.advanceTimersByTimeAsync(0))
      expect(result.current.data).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
}

function localConnectionsIsolationTests(): void {
  it('never leaks one project’s data across a project switch', async () => {
    vi.useFakeTimers()
    try {
      useWorkspaceStore.setState({ linked: true })
      const { result, rerender } = renderHook(({ id }) => useLocalConnections(id), {
        initialProps: { id: 'p1' }
      })
      await act(() => vi.advanceTimersByTimeAsync(0))
      expect(result.current.data).not.toBeNull()
      // Switch project: the p1 result must not render as p2's.
      mockedSources.mockReturnValue(new Promise(() => undefined))
      rerender({ id: 'p2' })
      expect(result.current.data).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('refresh re-fetches on demand', async () => {
    vi.useFakeTimers()
    try {
      useWorkspaceStore.setState({ linked: true })
      const { result } = renderHook(() => useLocalConnections('p1'))
      await act(() => vi.advanceTimersByTimeAsync(0))
      act(() => result.current.refresh())
      expect(mockedSources).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })
}
