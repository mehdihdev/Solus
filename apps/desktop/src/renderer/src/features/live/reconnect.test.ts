import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LiveStreamHttpError } from '../../lib/api/liveStream'
import { ApiError } from '../../lib/api/envelope.types'
import {
  RECONNECT_BASE_MS,
  RECONNECT_CAP_MS,
  backoffDelayMs,
  classifyStreamFailure,
  runReconnectingStream
} from './reconnect'

describe('backoffDelayMs (full jitter)', () => {
  it('draws uniformly from [0, min(cap, base * 2^attempt))', () => {
    expect(backoffDelayMs(0, () => 0)).toBe(0)
    expect(backoffDelayMs(0, () => 0.999999)).toBeLessThan(RECONNECT_BASE_MS)
    expect(backoffDelayMs(3, () => 0.5)).toBe(4_000)
  })
  it('never exceeds the 30 s cap, however many attempts', () => {
    for (const attempt of [5, 6, 20, 1_000]) {
      expect(backoffDelayMs(attempt, () => 0.999999)).toBeLessThan(RECONNECT_CAP_MS)
      expect(backoffDelayMs(attempt, () => 0.999999)).toBeGreaterThan(RECONNECT_CAP_MS - 10)
    }
  })
  it('is never negative for a negative attempt', () => {
    expect(backoffDelayMs(-4, () => 0.5)).toBe(500)
  })
})

describe('classifyStreamFailure', () => {
  it('401 waits for a new token', () => {
    expect(classifyStreamFailure(new LiveStreamHttpError(401))).toBe('await-token')
    expect(classifyStreamFailure(new ApiError(401, 'x', 'y'))).toBe('await-token')
  })
  it.each([403, 404])('%i stops for good', (status) => {
    expect(classifyStreamFailure(new LiveStreamHttpError(status))).toBe('stop')
    expect(classifyStreamFailure(new ApiError(status, 'x', 'y'))).toBe('stop')
  })
  it.each([429, 500, 502, 503])('%i backs off and retries', (status) => {
    expect(classifyStreamFailure(new LiveStreamHttpError(status))).toBe('retry')
  })
  it('retries network errors and non-error throws', () => {
    expect(classifyStreamFailure(new TypeError('network'))).toBe('retry')
    expect(classifyStreamFailure('boom')).toBe('retry')
    expect(classifyStreamFailure(null)).toBe('retry')
  })
})

describe('runReconnectingStream', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  const base = (
    controller: AbortController
  ): { signal: AbortSignal; isReady: (event: string) => boolean; random: () => number } => ({
    signal: controller.signal,
    isReady: (event: string) => event === 'ready',
    random: () => 0.5
  })

  it('reports connecting, then live on ready, and delivers events', async () => {
    const controller = new AbortController()
    const phases: string[] = []
    const events: string[] = []
    const done = runReconnectingStream({
      ...base(controller),
      open: async function* () {
        yield 'ready'
        yield 'x'
        await new Promise(() => undefined)
      },
      onEvent: (event) => void events.push(event),
      onPhase: (phase) => void phases.push(phase)
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(phases).toEqual(['connecting', 'live'])
    expect(events).toEqual(['ready', 'x'])
    controller.abort()
    await expect(done).resolves.toBe('aborted')
  })

  it('backs off exponentially after failures and resets after a successful ready', async () => {
    const controller = new AbortController()
    const opens: number[] = []
    let call = 0
    const phases: string[] = []
    const done = runReconnectingStream({
      ...base(controller),
      open: async function* () {
        opens.push(Date.now())
        call += 1
        if (call <= 2) throw new LiveStreamHttpError(503)
        if (call === 3) {
          yield 'ready'
          return
        }
        throw new LiveStreamHttpError(503)
      },
      onEvent: () => undefined,
      onPhase: (phase) => void phases.push(phase)
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(opens).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(499) // attempt 0 delay = 0.5 * 1000
    expect(opens).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(opens).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(999) // attempt 1 delay = 0.5 * 2000
    expect(opens).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(opens).toHaveLength(3) // ready, then the stream ends
    await vi.advanceTimersByTimeAsync(499) // reset -> attempt 0 delay again
    expect(opens).toHaveLength(3)
    await vi.advanceTimersByTimeAsync(1)
    expect(opens).toHaveLength(4)
    expect(phases[0]).toBe('connecting')
    expect(phases).toContain('live')
    expect(phases).toContain('reconnecting')
    controller.abort()
    await expect(done).resolves.toBe('aborted')
  })

  it('treats a clean end without ready as a failure (keeps growing the backoff)', async () => {
    const controller = new AbortController()
    let opens = 0
    const done = runReconnectingStream({
      ...base(controller),
      open: async function* () {
        opens += 1
        yield 'noise'
      },
      onEvent: () => undefined,
      onPhase: () => undefined
    })
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(500)
    expect(opens).toBe(2)
    await vi.advanceTimersByTimeAsync(1_000)
    expect(opens).toBe(3)
    controller.abort()
    await done
  })

  it('401 returns unauthorized without retrying', async () => {
    const controller = new AbortController()
    let opens = 0
    const done = runReconnectingStream({
      ...base(controller),
      open: async function* () {
        opens += 1
        throw new LiveStreamHttpError(401)
        yield 'ready'
      },
      onEvent: () => undefined,
      onPhase: () => undefined
    })
    await expect(done).resolves.toBe('unauthorized')
    await vi.advanceTimersByTimeAsync(120_000)
    expect(opens).toBe(1)
  })

  it.each([403, 404])('%i returns stopped without retrying', async (status) => {
    const controller = new AbortController()
    let opens = 0
    const done = runReconnectingStream({
      ...base(controller),
      open: async function* () {
        opens += 1
        throw new LiveStreamHttpError(status)
        yield 'ready'
      },
      onEvent: () => undefined,
      onPhase: () => undefined
    })
    await expect(done).resolves.toBe('stopped')
    await vi.advanceTimersByTimeAsync(120_000)
    expect(opens).toBe(1)
  })

  it('stops when the event handler asks to', async () => {
    const controller = new AbortController()
    let opens = 0
    const done = runReconnectingStream({
      ...base(controller),
      open: async function* () {
        opens += 1
        yield 'ready'
        yield 'revoked'
      },
      onEvent: (event) => (event === 'revoked' ? 'stop' : undefined),
      onPhase: () => undefined
    })
    await expect(done).resolves.toBe('stopped')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(opens).toBe(1)
  })

  it('aborting during the backoff wait ends the loop without another open', async () => {
    const controller = new AbortController()
    let opens = 0
    const done = runReconnectingStream({
      ...base(controller),
      open: async function* () {
        opens += 1
        throw new TypeError('network')
        yield 'ready'
      },
      onEvent: () => undefined,
      onPhase: () => undefined
    })
    await vi.advanceTimersByTimeAsync(10)
    controller.abort()
    await expect(done).resolves.toBe('aborted')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(opens).toBe(1)
  })

  it('does not open at all when already aborted', async () => {
    const controller = new AbortController()
    controller.abort()
    const open = vi.fn()
    await expect(
      runReconnectingStream({
        ...base(controller),
        open,
        onEvent: () => undefined,
        onPhase: () => undefined
      })
    ).resolves.toBe('aborted')
    expect(open).not.toHaveBeenCalled()
  })
})
