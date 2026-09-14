// Bridge pill state mapping + polling hook (SOLUSDEV-154 / BRG-03): pillState
// is a pure mapping; the hook polls every 10 s only while fetches are enabled
// and a project is linked, and degrades to null (offline) otherwise.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { pillState, useBridgeStatus, BRIDGE_POLL_MS } from './useBridgeStatus'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'
import type { BridgeServer, BridgeStatus } from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getBridgeStatus: vi.fn() }
})

function server(state: BridgeServer['state']): BridgeServer {
  return { name: 'github', state, detail: null, updated_at: '2026-07-23T00:00:00Z' }
}

function connected(servers: BridgeServer[]): BridgeStatus {
  return { connected: true, companion_version: '0.1.0', servers }
}

const OFFLINE: BridgeStatus = { connected: false, companion_version: null, servers: [] }

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
})

describe('pillState', () => {
  it('maps null and a disconnected companion to offline', () => {
    expect(pillState(null)).toBe('offline')
    expect(pillState(OFFLINE)).toBe('offline')
  })

  it('maps all-ready servers (or none) to ready', () => {
    expect(pillState(connected([]))).toBe('ready')
    expect(pillState(connected([server('ready'), server('launching')]))).toBe('ready')
  })

  it('maps any busy server to busy, even alongside errors', () => {
    expect(pillState(connected([server('ready'), server('busy')]))).toBe('busy')
    expect(pillState(connected([server('error'), server('busy')]))).toBe('busy')
  })

  it('maps error or not_launched servers to attention', () => {
    expect(pillState(connected([server('ready'), server('error')]))).toBe('attention')
    expect(pillState(connected([server('not_launched')]))).toBe('attention')
  })
})

describe('useBridgeStatus', () => {
  it('never polls while fetches are disabled (dev bypass, not linked)', () => {
    vi.useFakeTimers()
    try {
      renderHook(() => useBridgeStatus('p1'))
      vi.advanceTimersByTime(BRIDGE_POLL_MS * 3)
      expect(vi.mocked(resources.getBridgeStatus)).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('never polls without a project id', () => {
    vi.useFakeTimers()
    try {
      useWorkspaceStore.setState({ linked: true })
      renderHook(() => useBridgeStatus(null))
      vi.advanceTimersByTime(BRIDGE_POLL_MS * 3)
      expect(vi.mocked(resources.getBridgeStatus)).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('loads immediately, then re-polls every 10 s', async () => {
    vi.useFakeTimers()
    try {
      useWorkspaceStore.setState({ linked: true })
      vi.mocked(resources.getBridgeStatus).mockResolvedValue(connected([server('ready')]))
      const { result } = renderHook(() => useBridgeStatus('p1'))
      expect(vi.mocked(resources.getBridgeStatus)).toHaveBeenCalledTimes(1)
      expect(vi.mocked(resources.getBridgeStatus)).toHaveBeenCalledWith('p1')
      await act(() => vi.advanceTimersByTimeAsync(BRIDGE_POLL_MS))
      expect(vi.mocked(resources.getBridgeStatus)).toHaveBeenCalledTimes(2)
      expect(result.current?.connected).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('degrades to null (offline) when the API is unreachable', async () => {
    vi.useFakeTimers()
    try {
      useWorkspaceStore.setState({ linked: true })
      vi.mocked(resources.getBridgeStatus).mockRejectedValue(new Error('unreachable'))
      const { result } = renderHook(() => useBridgeStatus('p1'))
      await act(() => vi.advanceTimersByTimeAsync(0))
      expect(result.current).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})

it('keeps OS-incompatible servers neutral without hiding real launch failures', () => {
  const unavailable = { ...server('not_launched'), detail: 'Fusion is not available on Linux' }
  expect(pillState(connected([unavailable]))).toBe('ready')
  expect(pillState(connected([unavailable, server('error')]))).toBe('attention')
  expect(pillState(connected([{ ...unavailable, detail: 'failed to start' }]))).toBe('attention')
})
