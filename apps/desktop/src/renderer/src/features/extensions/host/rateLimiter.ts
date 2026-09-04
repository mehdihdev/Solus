// SOLUSDEV-235 / EXT-12 — per-extension request budget (extensions-runtime.md
// §6.5): 60 requests in a rolling 10 s window and 8 in flight, counted across
// every mounted frame of the extension in this renderer (a widget and a page
// share the budget). The clock is injectable so the window is provable.
import { BRIDGE_LIMITS } from './bridgeProtocol'

export interface RateLimiter {
  /** Admit one request now, or refuse. A refusal does not consume the window. */
  tryAcquire(): 'ok' | 'rate_limited'
  /** The admitted request finished (success or failure). */
  release(): void
  inFlight(): number
}

export interface RateLimiterOptions {
  now?: () => number
  windowMs?: number
  maxRequests?: number
  maxInFlight?: number
}

export function createRateLimiter(options: RateLimiterOptions = {}): RateLimiter {
  const now = options.now ?? Date.now
  const windowMs = options.windowMs ?? BRIDGE_LIMITS.windowMs
  const maxRequests = options.maxRequests ?? BRIDGE_LIMITS.windowRequests
  const maxInFlight = options.maxInFlight ?? BRIDGE_LIMITS.inFlight
  let admitted: number[] = []
  let inFlight = 0

  return {
    tryAcquire() {
      const t = now()
      admitted = admitted.filter((stamp) => t - stamp < windowMs)
      if (admitted.length >= maxRequests || inFlight >= maxInFlight) return 'rate_limited'
      admitted = [...admitted, t]
      inFlight += 1
      return 'ok'
    },
    release() {
      inFlight = Math.max(0, inFlight - 1)
    },
    inFlight: () => inFlight
  }
}

function sharedPool(make: () => RateLimiter): (extensionId: string) => RateLimiter {
  const pool = new Map<string, RateLimiter>()
  return (extensionId) => {
    const existing = pool.get(extensionId)
    if (existing) return existing
    const created = make()
    pool.set(extensionId, created)
    return created
  }
}

/** The renderer-wide limiter for an extension — every BridgeHost for the same
 *  id draws on the same budget. */
export const sharedRateLimiterFor = sharedPool(() => createRateLimiter())

/** SEC-C1: `ui.openExternal` has its own, much smaller budget (3 per 60 s per
 *  extension). Calls are counted, not held, so in-flight is unbounded here. */
export function createOpenExternalLimiter(now?: () => number): RateLimiter {
  return createRateLimiter({
    ...(now === undefined ? {} : { now }),
    windowMs: BRIDGE_LIMITS.openExternalWindowMs,
    maxRequests: BRIDGE_LIMITS.openExternalPerWindow,
    maxInFlight: Number.POSITIVE_INFINITY
  })
}

export const sharedOpenExternalLimiterFor = sharedPool(() => createOpenExternalLimiter())
