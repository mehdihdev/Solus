// SOLUSDEV-235 / EXT-12 — per-frame telemetry subscriptions (§6.5: at most 8
// per frame, samples batched to the frame at ≤ 10 events/s per subscription).
import type { TelemetrySample } from '../bridgeDeps'
import { BRIDGE_LIMITS } from '../bridgeProtocol'

export interface SampleBatch {
  readonly subscriptionId: string
  readonly samples: readonly TelemetrySample[]
}

export interface RegistryTimers {
  setTimeout(fn: () => void, ms: number): unknown
  clearTimeout(handle: unknown): void
}

export interface TelemetryRegistry {
  count(): number
  nextId(): string
  /** Register (or replace) the unsubscribe for `id`. */
  add(id: string, unsubscribe: () => void): void
  /** True when `id` was live; calls its unsubscribe and drops pending samples. */
  remove(id: string): boolean
  has(id: string): boolean
  /** Buffer samples; the batch is emitted on the next tick of the rate window. */
  push(id: string, samples: readonly TelemetrySample[]): void
  dispose(): void
}

const defaultTimers: RegistryTimers = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>)
}

export function createTelemetryRegistry(
  emit: (batch: SampleBatch) => void,
  timers: RegistryTimers = defaultTimers,
  intervalMs: number = 1000 / BRIDGE_LIMITS.telemetryEventsPerSecond
): TelemetryRegistry {
  const live = new Map<string, () => void>()
  const pending = new Map<string, TelemetrySample[]>()
  const timersById = new Map<string, unknown>()
  let counter = 0

  function flush(id: string): void {
    timersById.delete(id)
    const samples = pending.get(id)
    pending.delete(id)
    if (samples && samples.length > 0 && live.has(id)) emit({ subscriptionId: id, samples })
  }

  function drop(id: string): void {
    const handle = timersById.get(id)
    if (handle !== undefined) timers.clearTimeout(handle)
    timersById.delete(id)
    pending.delete(id)
  }

  return {
    count: () => live.size,
    nextId: () => `sub-${++counter}`,
    add: (id, unsubscribe) => void live.set(id, unsubscribe),
    has: (id) => live.has(id),
    remove(id) {
      const unsubscribe = live.get(id)
      if (!unsubscribe) return false
      live.delete(id)
      drop(id)
      unsubscribe()
      return true
    },
    push(id, samples) {
      if (!live.has(id)) return
      pending.set(id, [...(pending.get(id) ?? []), ...samples])
      if (!timersById.has(id))
        timersById.set(
          id,
          timers.setTimeout(() => flush(id), intervalMs)
        )
    },
    dispose() {
      for (const id of [...live.keys()]) {
        const unsubscribe = live.get(id)
        live.delete(id)
        drop(id)
        unsubscribe?.()
      }
    }
  }
}
