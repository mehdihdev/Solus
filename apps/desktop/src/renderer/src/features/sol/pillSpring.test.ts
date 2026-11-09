// SOLUSDEV-319: the panel-height spring. Retargeting keeps velocity, so a
// stream of small growths (one per wrapped line) reads as one continuous unroll.
import { describe, it, expect } from 'vitest'
import { SPRING_FRAME_MAX_S, settle, stepSpring, type SpringState } from './pillSpring'

const run = (state: SpringState, target: number, frames: number): SpringState => {
  let s = state
  for (let i = 0; i < frames; i += 1) s = stepSpring(s, target, 1 / 60)
  return s
}

describe('stepSpring', () => {
  it('moves toward the target without overshooting (critically damped)', () => {
    let s: SpringState = { x: 0, v: 0 }
    let peak = 0
    for (let i = 0; i < 120; i += 1) {
      s = stepSpring(s, 200, 1 / 60)
      peak = Math.max(peak, s.x)
    }
    expect(peak).toBeLessThanOrEqual(200.5)
    expect(s.x).toBeCloseTo(200, 0)
  })

  it('settles within about a third of a second', () => {
    const s = run({ x: 0, v: 0 }, 300, 24)
    expect(settle(s, 300)).toEqual({ x: 300, v: 0 })
  })

  it('keeps its velocity when the target moves mid-flight', () => {
    const moving = run({ x: 0, v: 0 }, 100, 6)
    const retargeted = stepSpring(moving, 140, 1 / 60)
    expect(moving.v).toBeGreaterThan(0)
    expect(retargeted.v).toBeGreaterThan(moving.v * 0.5)
  })

  it('clamps a long frame (a hidden window) so it cannot explode', () => {
    const s = stepSpring({ x: 0, v: 0 }, 400, 5)
    const clamped = stepSpring({ x: 0, v: 0 }, 400, SPRING_FRAME_MAX_S)
    expect(s).toEqual(clamped)
    expect(s.x).toBeLessThanOrEqual(400)
  })

  it('returns a new state and never mutates its input', () => {
    const input = Object.freeze({ x: 10, v: 0 })
    expect(stepSpring(input, 50, 1 / 60)).not.toBe(input)
  })
})

describe('settle', () => {
  it('is null while still moving', () => {
    expect(settle({ x: 150, v: 0 }, 200)).toBeNull()
    expect(settle({ x: 199.9, v: 40 }, 200)).toBeNull()
  })

  it('snaps to the target when close and slow', () => {
    expect(settle({ x: 199.8, v: 1 }, 200)).toEqual({ x: 200, v: 0 })
  })
})
