import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import * as resources from '../../lib/api/resources'
import { TELEOP_POLL_MS, useTeleopState } from './useTeleopState'
import { teleopFixture } from './teleopFixtures'

vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  getTeleop: vi.fn()
}))
const getTeleop = vi.mocked(resources.getTeleop)

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
})
afterEach(() => vi.useRealTimers())

describe('useTeleopState', () => {
  it('polls every second while enabled', async () => {
    getTeleop.mockResolvedValue(teleopFixture())
    const { result } = renderHook(() => useTeleopState('p1', true))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TELEOP_POLL_MS * 2)
    })
    expect(getTeleop.mock.calls.length).toBeGreaterThanOrEqual(3)
    expect(result.current.teleop?.id).toBe('t1')
  })
  it('does not poll when disabled', async () => {
    renderHook(() => useTeleopState('p1', false))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TELEOP_POLL_MS * 3)
    })
    expect(getTeleop).not.toHaveBeenCalled()
  })
  it('keeps the last state when a poll fails', async () => {
    getTeleop.mockResolvedValueOnce(teleopFixture())
    getTeleop.mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useTeleopState('p1', true))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TELEOP_POLL_MS * 2)
    })
    expect(result.current.teleop?.id).toBe('t1')
  })
})
