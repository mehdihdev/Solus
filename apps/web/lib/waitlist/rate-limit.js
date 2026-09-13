/**
 * Fixed-window in-memory rate limiter.
 *
 * Deliberately dependency-free so the marketing site stays deployable to Vercel
 * on its own. The tradeoff: serverless instances do not share memory, so the
 * effective limit is per warm instance rather than global. That is enough to
 * blunt a burst from one client; it is not a defence against a distributed
 * attack. Swap in a Redis-backed limiter if this ever needs to be authoritative.
 */

const WINDOW_MS = 10 * 60 * 1000;
const MAX_REQUESTS_PER_WINDOW = 5;
const MAX_TRACKED_CLIENTS = 10_000;

const hits = new Map();

function sweep(now) {
  for (const [key, entry] of hits) {
    if (entry.resetAt <= now) {
      hits.delete(key);
    }
  }

  // Hard bound on memory even if the sweep cannot keep up under a flood.
  if (hits.size > MAX_TRACKED_CLIENTS) {
    hits.clear();
  }
}

/**
 * @param {string} clientKey
 * @param {number} [now]
 * @returns {{ allowed: boolean, remaining: number, retryAfterSeconds: number }}
 */
export function consume(clientKey, now = Date.now()) {
  sweep(now);

  const entry = hits.get(clientKey);

  if (!entry || entry.resetAt <= now) {
    hits.set(clientKey, { count: 1, resetAt: now + WINDOW_MS });

    return {
      allowed: true,
      remaining: MAX_REQUESTS_PER_WINDOW - 1,
      retryAfterSeconds: 0,
    };
  }

  if (entry.count >= MAX_REQUESTS_PER_WINDOW) {
    return {
      allowed: false,
      remaining: 0,
      retryAfterSeconds: Math.max(1, Math.ceil((entry.resetAt - now) / 1000)),
    };
  }

  entry.count += 1;

  return {
    allowed: true,
    remaining: MAX_REQUESTS_PER_WINDOW - entry.count,
    retryAfterSeconds: 0,
  };
}

/** Test seam — drops all tracked clients. */
export function resetRateLimiter() {
  hits.clear();
}

export const RATE_LIMIT = {
  WINDOW_MS,
  MAX_REQUESTS_PER_WINDOW,
};
