// SOLUSDEV-252 S2-A: token text coalesces into ONE flush per animation frame;
// every other stream event flushes pending text first so ordering holds.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MAX_TURN_CHARS } from './solChatStore'
import { createTokenBatcher } from './tokenBatcher'

/** A manual frame scheduler: collects callbacks; `frame()` runs them all. */
function manualSchedule(): {
  schedule: (cb: () => void) => void
  frame: () => void
  calls: number
} {
  const queued: Array<() => void> = []
  const api = {
    calls: 0,
    schedule: (cb: () => void) => {
      api.calls++
      queued.push(cb)
    },
    frame: () => {
      for (const cb of queued.splice(0)) cb()
    }
  }
  return api
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('createTokenBatcher', () => {
  it('coalesces N tokens into one flush per frame', () => {
    const flush = vi.fn()
    const s = manualSchedule()
    const batcher = createTokenBatcher(flush, s.schedule)
    for (let i = 0; i < 50; i++) batcher.push(`t${i} `)
    expect(flush).not.toHaveBeenCalled()
    expect(s.calls).toBe(1) // one frame requested, not fifty
    s.frame()
    expect(flush).toHaveBeenCalledTimes(1)
    expect(flush).toHaveBeenCalledWith(Array.from({ length: 50 }, (_, i) => `t${i} `).join(''))
    // The next token opens a NEW frame.
    batcher.push('more')
    expect(s.calls).toBe(2)
    s.frame()
    expect(flush).toHaveBeenCalledTimes(2)
    expect(flush).toHaveBeenLastCalledWith('more')
  })

  it('flushNow delivers pending text synchronously and the frame then flushes nothing', () => {
    const flush = vi.fn()
    const s = manualSchedule()
    const batcher = createTokenBatcher(flush, s.schedule)
    batcher.push('a')
    batcher.push('b')
    batcher.flushNow()
    expect(flush).toHaveBeenCalledTimes(1)
    expect(flush).toHaveBeenCalledWith('ab')
    s.frame()
    expect(flush).toHaveBeenCalledTimes(1) // empty buffer never notifies
    batcher.flushNow()
    expect(flush).toHaveBeenCalledTimes(1)
  })

  it('dispose drops the pending frame and ignores later pushes', () => {
    const flush = vi.fn()
    const s = manualSchedule()
    const batcher = createTokenBatcher(flush, s.schedule)
    batcher.push('doomed')
    batcher.dispose()
    s.frame()
    batcher.push('late')
    batcher.flushNow()
    expect(flush).not.toHaveBeenCalled()
  })

  it('falls back to setTimeout when requestAnimationFrame is absent', () => {
    vi.useFakeTimers()
    vi.stubGlobal('requestAnimationFrame', undefined)
    const flush = vi.fn()
    const batcher = createTokenBatcher(flush)
    batcher.push('x')
    expect(flush).not.toHaveBeenCalled()
    vi.advanceTimersByTime(20)
    expect(flush).toHaveBeenCalledWith('x')
  })

  it('bounds the in-flight buffer at MAX_TURN_CHARS (SEC-H3)', () => {
    const flush = vi.fn()
    const s = manualSchedule()
    const batcher = createTokenBatcher(flush, s.schedule, MAX_TURN_CHARS)
    for (let i = 0; i < 5; i++) batcher.push('x'.repeat(100_000))
    s.frame()
    expect(flush).toHaveBeenCalledTimes(1)
    expect(String(flush.mock.calls[0][0]).length).toBeLessThanOrEqual(MAX_TURN_CHARS + 100_000) // one over-run push, then capped
  })
})
