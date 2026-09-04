// SOLUSDEV-235 / SEC-H4+M1 — the `extension.bridge_refused` data-collection
// hook (§6.4). Refusals are queued and flushed as ONE batched POST through the
// typed client (API.md §2.13), under a per-extension budget so a frame that
// spams refusals cannot turn the event route into a second flood: past 20 in
// a rolling 60 s the refusal is still answered to the frame but the event is
// dropped and counted here.
import { postDataEvents, type DataEventInput } from '../../../lib/api/resources.extensions'
import type { BridgeRefusal } from './bridgeDeps'
import { createRateLimiter, type RateLimiter } from './rateLimiter'

export const REFUSAL_EVENT = 'extension.bridge_refused'
export const REFUSAL_BUDGET = { windowMs: 60_000, maxEvents: 20 } as const
const FLUSH_DELAY_MS = 2_000

export interface RefusalReporterOptions {
  post?: (events: readonly DataEventInput[]) => Promise<void>
  now?: () => number
  /** Defer a flush; defaults to setTimeout. */
  schedule?: (fn: () => void, ms: number) => void
  /** The open project, stamped on every event when known. */
  projectId?: () => string | undefined
}

export interface RefusalReporter {
  emit(refusal: BridgeRefusal): void
  /** Post whatever is queued now (the scheduled flush calls this). */
  flush(): Promise<void>
  stats(): { queued: number; dropped: number }
}

function toEvent(refusal: BridgeRefusal, projectId: string | undefined): DataEventInput {
  return {
    event_type: REFUSAL_EVENT,
    ...(projectId === undefined ? {} : { project_id: projectId }),
    payload: {
      slug: refusal.extensionId,
      version: refusal.version,
      method: refusal.method,
      code: refusal.code
    }
  }
}

export function createRefusalReporter(options: RefusalReporterOptions = {}): RefusalReporter {
  const post = options.post ?? postDataEvents
  const now = options.now ?? Date.now
  const schedule = options.schedule ?? ((fn, ms) => void setTimeout(fn, ms))
  const projectId = options.projectId ?? (() => undefined)
  const budgets = new Map<string, RateLimiter>()
  let queue: DataEventInput[] = []
  let dropped = 0
  let flushPending = false

  const budgetFor = (extensionId: string): RateLimiter => {
    const existing = budgets.get(extensionId)
    if (existing) return existing
    const created = createRateLimiter({
      now,
      windowMs: REFUSAL_BUDGET.windowMs,
      maxRequests: REFUSAL_BUDGET.maxEvents,
      maxInFlight: Number.POSITIVE_INFINITY
    })
    budgets.set(extensionId, created)
    return created
  }

  async function flush(): Promise<void> {
    flushPending = false
    if (queue.length === 0) return
    const batch = queue
    queue = []
    try {
      await post(batch)
    } catch {
      // Data collection is best-effort: a failed batch is dropped, never retried
      // (a retry loop would be its own flood) and never surfaced to the frame.
      dropped += batch.length
    }
  }

  return {
    emit(refusal) {
      const budget = budgetFor(refusal.extensionId)
      if (budget.tryAcquire() === 'rate_limited') {
        dropped += 1
        return
      }
      budget.release()
      queue = [...queue, toEvent(refusal, projectId())]
      if (flushPending) return
      flushPending = true
      schedule(() => void flush(), FLUSH_DELAY_MS)
    },
    flush,
    stats: () => ({ queued: queue.length, dropped })
  }
}
