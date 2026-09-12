import { describe, expect, it, vi } from 'vitest'
import { SAMPLE_INTERVAL_MS, createCursorSampler } from './cursorSampler'

function fakeScheduler(): {
  scheduler: {
    setInterval: (cb: () => void, ms: number) => unknown
    clearInterval: (h: unknown) => void
  }
  tick(): void
  active(): number
} {
  const timers = new Map<number, () => void>()
  let next = 1
  return {
    scheduler: {
      setInterval: (cb) => {
        const id = next++
        timers.set(id, cb)
        return id
      },
      clearInterval: (h) => void timers.delete(h as number)
    },
    tick: () => timers.forEach((cb) => cb()),
    active: () => timers.size
  }
}

describe('cursorSampler', () => {
  it('never polls the cursor while idle', () => {
    const s = fakeScheduler()
    const getCursor = vi.fn(() => ({ x: 0, y: 0 }))
    createCursorSampler({ getCursor, now: () => 0, scheduler: s.scheduler, onSample: vi.fn() })
    s.tick()
    expect(getCursor).not.toHaveBeenCalled()
    expect(s.active()).toBe(0)
  })

  it('polls at ~60 Hz while armed and stops on disarm', () => {
    const s = fakeScheduler()
    let t = 0
    const onSample = vi.fn()
    const sampler = createCursorSampler({
      getCursor: () => ({ x: t, y: 1 }),
      now: () => t,
      scheduler: s.scheduler,
      onSample
    })
    expect(SAMPLE_INTERVAL_MS).toBeLessThanOrEqual(17)
    sampler.arm()
    sampler.arm() // idempotent: one interval
    expect(s.active()).toBe(1)
    t = 16
    s.tick()
    t = 32
    s.tick()
    expect(onSample.mock.calls).toEqual([
      [16, { x: 16, y: 1 }],
      [32, { x: 32, y: 1 }]
    ])
    sampler.disarm()
    expect(s.active()).toBe(0)
    expect(sampler.isArmed()).toBe(false)
    s.tick()
    expect(onSample).toHaveBeenCalledTimes(2)
  })
})
