// SOLUSDEV-235 / EXT-12 — per-frame subscriptions and ≤ 10 events/s batching (§6.5).
import { describe, it, expect, vi } from 'vitest'
import { createTelemetryRegistry, type RegistryTimers, type SampleBatch } from './telemetryRegistry'

function manualTimers(): RegistryTimers & { fire(): void; pending(): number } {
  const queue: (() => void)[] = []
  return {
    setTimeout: (fn) => {
      queue.push(fn)
      return fn
    },
    clearTimeout: (handle) => {
      const i = queue.indexOf(handle as () => void)
      if (i >= 0) queue.splice(i, 1)
    },
    fire: () => {
      const fns = queue.splice(0)
      fns.forEach((fn) => fn())
    },
    pending: () => queue.length
  }
}

describe('createTelemetryRegistry', () => {
  it('batches pushes into one event per interval per subscription', () => {
    const emitted: SampleBatch[] = []
    const timers = manualTimers()
    const registry = createTelemetryRegistry((b) => emitted.push(b), timers, 100)
    const id = registry.nextId()
    registry.add(id, () => undefined)
    registry.push(id, [{ signalId: 'a', t: 1, value: 1 }])
    registry.push(id, [{ signalId: 'a', t: 2, value: 2 }])
    expect(emitted).toEqual([])
    expect(timers.pending()).toBe(1)
    timers.fire()
    expect(emitted).toEqual([
      {
        subscriptionId: id,
        samples: [
          { signalId: 'a', t: 1, value: 1 },
          { signalId: 'a', t: 2, value: 2 }
        ]
      }
    ])
  })

  it('ignores pushes for unknown ids and drops pending samples on remove', () => {
    const emitted: SampleBatch[] = []
    const timers = manualTimers()
    const registry = createTelemetryRegistry((b) => emitted.push(b), timers)
    registry.push('ghost', [{ signalId: 'a', t: 1, value: 1 }])
    expect(timers.pending()).toBe(0)
    const unsubscribe = vi.fn()
    registry.add('s1', unsubscribe)
    registry.push('s1', [{ signalId: 'a', t: 1, value: 1 }])
    expect(registry.remove('s1')).toBe(true)
    expect(unsubscribe).toHaveBeenCalledTimes(1)
    expect(timers.pending()).toBe(0)
    timers.fire()
    expect(emitted).toEqual([])
    expect(registry.remove('s1')).toBe(false)
  })

  it('dispose unsubscribes everything', () => {
    const registry = createTelemetryRegistry(() => undefined, manualTimers())
    const a = vi.fn()
    const b = vi.fn()
    registry.add('a', a)
    registry.add('b', b)
    expect(registry.count()).toBe(2)
    registry.dispose()
    expect(a).toHaveBeenCalled()
    expect(b).toHaveBeenCalled()
    expect(registry.count()).toBe(0)
  })

  it('ids are unique per registry', () => {
    const registry = createTelemetryRegistry(() => undefined, manualTimers())
    expect(registry.nextId()).not.toBe(registry.nextId())
  })
})
