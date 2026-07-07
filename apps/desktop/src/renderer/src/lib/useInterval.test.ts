import { describe, it, expect, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useInterval } from './useInterval'

describe('useInterval', () => {
  it('invokes the latest callback on each tick and stops on unmount', () => {
    vi.useFakeTimers()
    try {
      const fn = vi.fn()
      const { unmount } = renderHook(() => useInterval(fn, 100))
      vi.advanceTimersByTime(350)
      expect(fn).toHaveBeenCalledTimes(3)
      unmount()
      vi.advanceTimersByTime(300)
      expect(fn).toHaveBeenCalledTimes(3)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not tick when disabled', () => {
    vi.useFakeTimers()
    try {
      const fn = vi.fn()
      renderHook(() => useInterval(fn, 100, false))
      vi.advanceTimersByTime(500)
      expect(fn).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })
})
