// SOLUSDEV-235 / EXT-12 — 60 requests / rolling 10 s and 8 in flight, per
// extension across all of its frames (extensions-runtime.md §6.5).
import { describe, it, expect } from 'vitest'
import { BRIDGE_LIMITS } from './bridgeProtocol'
import { createRateLimiter, sharedRateLimiterFor } from './rateLimiter'

function clock(start = 0): { now: () => number; advance: (ms: number) => void } {
  let t = start
  return { now: () => t, advance: (ms) => (t += ms) }
}

describe('createRateLimiter', () => {
  it('admits up to the window cap, then refuses until the window slides', () => {
    const c = clock()
    const limiter = createRateLimiter({ now: c.now })
    for (let i = 0; i < BRIDGE_LIMITS.windowRequests; i++) {
      expect(limiter.tryAcquire()).toBe('ok')
      limiter.release()
    }
    expect(limiter.tryAcquire()).toBe('rate_limited')
    c.advance(BRIDGE_LIMITS.windowMs - 1)
    expect(limiter.tryAcquire()).toBe('rate_limited')
    c.advance(2)
    expect(limiter.tryAcquire()).toBe('ok')
  })

  it('a refused attempt does not consume the window (the limiter is not rate limited)', () => {
    const c = clock()
    const limiter = createRateLimiter({ now: c.now, maxRequests: 2 })
    limiter.tryAcquire()
    limiter.release()
    limiter.tryAcquire()
    limiter.release()
    for (let i = 0; i < 100; i++) expect(limiter.tryAcquire()).toBe('rate_limited')
    c.advance(BRIDGE_LIMITS.windowMs + 1)
    expect(limiter.tryAcquire()).toBe('ok')
  })

  it('caps in-flight requests at 8 independently of the window', () => {
    const limiter = createRateLimiter({ now: () => 0 })
    for (let i = 0; i < BRIDGE_LIMITS.inFlight; i++) expect(limiter.tryAcquire()).toBe('ok')
    expect(limiter.inFlight()).toBe(BRIDGE_LIMITS.inFlight)
    expect(limiter.tryAcquire()).toBe('rate_limited')
    limiter.release()
    expect(limiter.tryAcquire()).toBe('ok')
  })

  it('release never goes below zero', () => {
    const limiter = createRateLimiter({ now: () => 0 })
    limiter.release()
    limiter.release()
    expect(limiter.inFlight()).toBe(0)
  })
})

describe('sharedRateLimiterFor', () => {
  it('returns one limiter per extension id so frames share a budget', () => {
    const a = sharedRateLimiterFor('shared-a')
    expect(sharedRateLimiterFor('shared-a')).toBe(a)
    expect(sharedRateLimiterFor('shared-b')).not.toBe(a)
  })
})
