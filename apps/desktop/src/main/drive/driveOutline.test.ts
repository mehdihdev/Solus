// SOLUSDEV-319 drive slice 3 (sol-drive.md §5 "While a step runs"): the amber
// outline sits just OUTSIDE the driven window — never over it, which the
// helper's hit-test would refuse — and the hotkey detectors stay quiet while a
// step runs and 300 ms after.
import { describe, expect, it, vi } from 'vitest'
import {
  createDriveSession,
  DRIVE_QUIET_TAIL_MS,
  DRIVE_SAFETY_TIMEOUT_MS,
  OUTLINE_THICKNESS_PX,
  outlineStrips,
  type OutlineStrip
} from './driveOutline'

const T = OUTLINE_THICKNESS_PX
type R = { x: number; y: number; width: number; height: number }
const overlaps = (a: R, b: R): boolean =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height

describe('outlineStrips', () => {
  it('four strips hugging the window from outside', () => {
    const w = { x: 100, y: 50, width: 800, height: 600 }
    expect(outlineStrips(w)).toEqual([
      { x: 100 - T, y: 50 - T, width: 800 + 2 * T, height: T },
      { x: 100 - T, y: 650, width: 800 + 2 * T, height: T },
      { x: 100 - T, y: 50, width: T, height: 600 },
      { x: 900, y: 50, width: T, height: 600 }
    ])
  })

  it('rounds outward to whole pixels and never overlaps the window', () => {
    const w = { x: 10.4, y: 20.6, width: 300.3, height: 200.2 }
    const strips = outlineStrips(w)
    for (const s of strips) {
      expect([s.x, s.y, s.width, s.height].every(Number.isInteger)).toBe(true)
      expect(overlaps(s, w)).toBe(false)
    }
    // …and closes around it: the outer edges enclose the window.
    expect(strips[0].x).toBeLessThanOrEqual(w.x - T + 1)
    expect(strips[3].x).toBeGreaterThanOrEqual(w.x + w.width)
  })
})

function harness(): {
  strips: Array<OutlineStrip & { bounds: R | null; shown: boolean; destroyed: boolean }>
  advance(ms: number): void
  session: ReturnType<typeof createDriveSession>
} {
  let t = 0
  let timer: { cb: () => void; due: number } | null = null
  const strips: Array<OutlineStrip & { bounds: R | null; shown: boolean; destroyed: boolean }> = []
  const session = createDriveSession({
    createStrip: () => {
      const s = {
        bounds: null as R | null,
        shown: false,
        destroyed: false,
        setBounds: (b: R) => void (s.bounds = b),
        showInactive: () => void (s.shown = true),
        hide: () => void (s.shown = false),
        destroy: () => void (s.destroyed = true),
        isDestroyed: () => s.destroyed
      }
      strips.push(s)
      return s
    },
    now: () => t,
    setTimeout: (cb, ms) => {
      timer = { cb, due: t + ms }
      return timer
    },
    clearTimeout: (h) => {
      if (h === timer) timer = null
    }
  })
  return {
    strips,
    session,
    advance(ms) {
      t += ms
      if (timer && timer.due <= t) {
        const { cb } = timer
        timer = null
        cb()
      }
    }
  }
}

const W = { x: 0, y: 0, width: 100, height: 100 }

describe('createDriveSession', () => {
  it('draws nothing until driving AND bounds are known', () => {
    const h = harness()
    h.session.setBounds(W)
    expect(h.strips).toHaveLength(0)
    h.session.setDriving(1, true)
    expect(h.strips).toHaveLength(4)
    expect(h.strips.every((s) => s.shown)).toBe(true)
    expect(h.strips.map((s) => s.bounds)).toEqual(outlineStrips(W))
  })

  it('follows the window when its bounds change', () => {
    const h = harness()
    h.session.setDriving(1, true)
    expect(h.strips).toHaveLength(0)
    h.session.setBounds(W)
    const moved = { ...W, x: 40 }
    h.session.setBounds(moved)
    expect(h.strips).toHaveLength(4)
    expect(h.strips.map((s) => s.bounds)).toEqual(outlineStrips(moved))
  })

  it('end() forgets the bounds: the next step does not flash the old outline', () => {
    const h = harness()
    h.session.setBounds(W)
    h.session.setDriving(1, true)
    h.session.setDriving(1, false)
    h.session.setDriving(1, true)
    expect(h.strips.every((s) => !s.shown)).toBe(true)
    h.session.setBounds({ ...W, x: 7 })
    expect(h.strips.every((s) => s.shown)).toBe(true)
  })

  it('ref-counts senders: active while any says true; a released sender counts as false', () => {
    const h = harness()
    h.session.setBounds(W)
    h.session.setDriving(1, true)
    h.session.setDriving(2, true)
    h.session.setDriving(1, false)
    expect(h.session.isQuiet()).toBe(true)
    expect(h.strips.every((s) => s.shown)).toBe(true)
    h.session.setDriving(2, true) // repeated true is idempotent
    h.session.releaseSender(2) // its window closed
    expect(h.strips.every((s) => !s.shown)).toBe(true)
    h.advance(DRIVE_QUIET_TAIL_MS)
    expect(h.session.isQuiet()).toBe(false)
  })

  it('a false from a sender that never said true changes nothing', () => {
    const h = harness()
    h.session.setBounds(W)
    h.session.setDriving(1, true)
    h.session.setDriving(9, false)
    h.session.releaseSender(9)
    expect(h.strips.every((s) => s.shown)).toBe(true)
  })

  it('clears on setDriving(false), and bounds do not redraw it afterwards', () => {
    const h = harness()
    h.session.setBounds(W)
    h.session.setDriving(1, true)
    h.session.setDriving(1, false)
    expect(h.strips.every((s) => !s.shown)).toBe(true)
    h.session.setBounds({ ...W, y: 5 })
    expect(h.strips.every((s) => !s.shown)).toBe(true)
  })

  it('quiet while driving and for the tail after, then not', () => {
    const h = harness()
    expect(h.session.isQuiet()).toBe(false)
    h.session.setDriving(1, true)
    expect(h.session.isQuiet()).toBe(true)
    h.session.setDriving(1, false)
    h.advance(DRIVE_QUIET_TAIL_MS - 1)
    expect(h.session.isQuiet()).toBe(true)
    h.advance(1)
    expect(h.session.isQuiet()).toBe(false)
  })

  it('ends itself after the safety timeout if the renderer never says so', () => {
    const h = harness()
    h.session.setBounds(W)
    h.session.setDriving(1, true)
    h.advance(DRIVE_SAFETY_TIMEOUT_MS)
    expect(h.strips.every((s) => !s.shown)).toBe(true)
    h.advance(DRIVE_QUIET_TAIL_MS)
    expect(h.session.isQuiet()).toBe(false)
  })

  it('a renewed setDriving(true) restarts the safety clock', () => {
    const h = harness()
    h.session.setBounds(W)
    h.session.setDriving(1, true)
    h.advance(DRIVE_SAFETY_TIMEOUT_MS - 10)
    h.session.setDriving(1, true)
    h.advance(20)
    expect(h.strips.every((s) => s.shown)).toBe(true)
  })

  it('dispose destroys the strips and ends the session', () => {
    const h = harness()
    h.session.setBounds(W)
    h.session.setDriving(1, true)
    h.session.dispose()
    expect(h.strips.every((s) => s.destroyed)).toBe(true)
  })

  it('a strip destroyed from outside is recreated on the next draw', () => {
    const h = harness()
    h.session.setBounds(W)
    h.session.setDriving(1, true)
    h.strips[0].destroy()
    h.session.setBounds({ ...W, x: 1 })
    expect(h.strips).toHaveLength(5)
  })
})

describe('session spy safety', () => {
  it('never throws when a strip call fails', () => {
    const session = createDriveSession({
      createStrip: () => ({
        setBounds: vi.fn(() => {
          throw new Error('gone')
        }),
        showInactive: vi.fn(),
        hide: vi.fn(),
        destroy: vi.fn(),
        isDestroyed: () => false
      }),
      now: () => 0,
      setTimeout: () => 0,
      clearTimeout: () => undefined
    })
    session.setBounds(W)
    expect(() => session.setDriving(1, true)).not.toThrow()
  })
})
