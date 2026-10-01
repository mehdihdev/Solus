// Reconnect policy shared by the live channels (ADR-037): full-jitter
// exponential backoff, plus the failure classification the wireflow asks for —
// permission failures stop retrying, an expired token waits for a new one.
// Pure of React so it is unit-testable with fake timers.

export const RECONNECT_BASE_MS = 1_000
export const RECONNECT_CAP_MS = 30_000

/** `await-token`: 401 — retrying with the same token is pointless; the owning
 *  hook restarts when authStore hands it a fresh one. `stop`: 403/404. */
export type FailureAction = 'retry' | 'await-token' | 'stop'
export type StreamPhase = 'connecting' | 'live' | 'reconnecting'
export type StreamOutcome = 'aborted' | 'stopped' | 'unauthorized'

/** A uniformly random wait in [0, min(cap, base * 2^attempt)). */
export function backoffDelayMs(attempt: number, random: () => number = Math.random): number {
  const exponent = Math.max(0, attempt)
  const ceiling = Math.min(RECONNECT_CAP_MS, RECONNECT_BASE_MS * 2 ** Math.min(exponent, 30))
  return Math.floor(random() * ceiling)
}

function statusOf(cause: unknown): number | null {
  if (typeof cause !== 'object' || cause === null || !('status' in cause)) return null
  const { status } = cause
  return typeof status === 'number' ? status : null
}

export function classifyStreamFailure(cause: unknown): FailureAction {
  const status = statusOf(cause)
  if (status === 401) return 'await-token'
  if (status === 403 || status === 404) return 'stop'
  return 'retry'
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve()
    const finish = (): void => {
      clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }
    const timer = setTimeout(finish, ms)
    signal.addEventListener('abort', finish)
  })
}

const ABORTED = Symbol('aborted')

/** Race a pending read against abort so a stalled stream can never hold the loop. */
async function nextOrAbort<T>(
  iterator: AsyncIterator<T>,
  signal: AbortSignal
): Promise<IteratorResult<T> | typeof ABORTED> {
  if (signal.aborted) return ABORTED
  let onAbort: () => void = () => undefined
  const aborted = new Promise<typeof ABORTED>((resolve) => {
    onAbort = () => resolve(ABORTED)
    signal.addEventListener('abort', onAbort, { once: true })
  })
  try {
    return await Promise.race([iterator.next(), aborted])
  } finally {
    signal.removeEventListener('abort', onAbort)
  }
}

/** Drain one connection. Returns a final outcome, or null when it simply ended. */
async function consume<T>(
  options: ReconnectingStreamOptions<T>,
  onHealthy: () => void
): Promise<StreamOutcome | null> {
  const iterator = options.open(options.signal)[Symbol.asyncIterator]()
  try {
    for (;;) {
      const step = await nextOrAbort(iterator, options.signal)
      if (step === ABORTED) return 'aborted'
      if (step.done) return null
      if (options.isReady(step.value)) {
        onHealthy()
        options.onPhase('live')
      }
      if (options.onEvent(step.value) === 'stop') return 'stopped'
    }
  } finally {
    void Promise.resolve(iterator.return?.()).catch(() => undefined)
  }
}

export interface ReconnectingStreamOptions<T> {
  open: (signal: AbortSignal) => AsyncIterable<T>
  /** The event that proves the stream is healthy; it resets the backoff. */
  isReady: (event: T) => boolean
  /** Return `'stop'` to end the loop for good (e.g. access revoked). */
  onEvent: (event: T) => 'stop' | void
  onPhase: (phase: StreamPhase) => void
  signal: AbortSignal
  random?: () => number
}

/** Keep one stream open until aborted, stopped, or unauthorized. Never throws. */
export async function runReconnectingStream<T>(
  options: ReconnectingStreamOptions<T>
): Promise<StreamOutcome> {
  const { signal, random } = options
  let attempt = 0
  let first = true
  while (!signal.aborted) {
    options.onPhase(first ? 'connecting' : 'reconnecting')
    first = false
    try {
      const verdict = await consume(options, () => {
        attempt = 0
      })
      if (verdict) return verdict
    } catch (cause) {
      if (signal.aborted) return 'aborted'
      const action = classifyStreamFailure(cause)
      if (action === 'stop') return 'stopped'
      if (action === 'await-token') return 'unauthorized'
    }
    if (signal.aborted) return 'aborted'
    options.onPhase('reconnecting')
    await wait(backoffDelayMs(attempt, random), signal)
    attempt += 1
  }
  return 'aborted'
}
