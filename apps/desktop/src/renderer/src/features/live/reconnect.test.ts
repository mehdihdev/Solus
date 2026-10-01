import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LiveStreamHttpError } from '../../lib/api/liveStream'
import { ApiError } from '../../lib/api/envelope.types'
import {
  RECONNECT_BASE_MS,
  RECONNECT_CAP_MS,
  STABLE_AFTER_READY_MS,
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

  it('backs off exponentially and resets only after the stream stayed up for the stable period', async () => {
    const controller = new AbortController()
    const opens: number[] = []
    let call = 0
    const done = runReconnectingStream({
      ...base(controller),
      open: async function* () {
        opens.push(Date.now())
        call += 1
        if (call <= 2) throw new LiveStreamHttpError(503)
        if (call === 3) {
          yield 'ready'
          await new Promise((resolve) => setTimeout(resolve, STABLE_AFTER_READY_MS + 1))
          return
        }
        throw new LiveStreamHttpError(503)
      },
      onEvent: () => undefined,
      onPhase: () => undefined
    })
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(500) // attempt 0 delay = 0.5 * 1000
    expect(opens).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(1_000) // attempt 1 delay = 0.5 * 2000
    expect(opens).toHaveLength(3)
    await vi.advanceTimersByTimeAsync(STABLE_AFTER_READY_MS + 1) // stable, then ends
    await vi.advanceTimersByTimeAsync(499) // reset -> attempt 0 delay again
    expect(opens).toHaveLength(3)
    await vi.advanceTimersByTimeAsync(1)
    expect(opens).toHaveLength(4)
    controller.abort()
    await expect(done).resolves.toBe('aborted')
  })

  it('keeps growing the delay when the server closes right after ready (no reconnect storm)', async () => {
    const controller = new AbortController()
    let opens = 0
    const done = runReconnectingStream({
      ...base(controller),
      open: async function* () {
        opens += 1
        yield 'ready'
      },
      onEvent: () => undefined,
      onPhase: () => undefined
    })
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(500) // attempt 0
    expect(opens).toBe(2)
    await vi.advanceTimersByTimeAsync(999) // attempt 1 ceiling 2000 * 0.5
    expect(opens).toBe(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(opens).toBe(3)
    await vi.advanceTimersByTimeAsync(1_999) // attempt 2 = 0.5 * 4000
    expect(opens).toBe(3)
    await vi.advanceTimersByTimeAsync(1)
    expect(opens).toBe(4)
    controller.abort()
    await done
  })

  it('calls onStable once the stream has been up for the stable period, not before', async () => {
    const controller = new AbortController()
    const onStable = vi.fn()
    const done = runReconnectingStream({
      ...base(controller),
      open: async function* () {
        yield 'ready'
        await new Promise(() => undefined)
      },
      onEvent: () => undefined,
      onPhase: () => undefined,
      onStable
    })
    await vi.advanceTimersByTimeAsync(STABLE_AFTER_READY_MS - 1)
    expect(onStable).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(onStable).toHaveBeenCalledTimes(1)
    controller.abort()
    await done
  })

  it('reconnect-now reopens immediately without growing the backoff', async () => {
    const controller = new AbortController()
    let opens = 0
    const done = runReconnectingStream({
      ...base(controller),
      open: async function* () {
        opens += 1
        yield 'ready'
        yield 'revoked'
        await new Promise(() => undefined)
      },
      onEvent: (event) => (event === 'revoked' && opens === 1 ? 'reconnect-now' : undefined),
      onPhase: () => undefined
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(opens).toBe(2)
    controller.abort()
    await done
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
