// SOLUSDEV-319: the Ember Pill's placement — summoned next to the cursor, grown
// upward with its bottom edge fixed, shifted aside so it never covers the point
// the pointer was on (docs/wireflows/sol-window.md "SOLUSDEV-319 Ember Pill").
import { describe, it, expect } from 'vitest'
import {
  growPill,
  placePill,
  SOL_PILL_CURSOR_OFFSET,
  SOL_PILL_MAX_HEIGHT,
  SOL_PILL_MIN_HEIGHT,
  SOL_PILL_WIDTH
} from './pillGeometry'

const WA = { x: 0, y: 0, width: 1920, height: 1040 }
const SIZE = { width: SOL_PILL_WIDTH, height: 96 }

describe('placePill', () => {
  it('sits below-left of the cursor by the offset', () => {
    expect(placePill({ x: 600, y: 300 }, WA, SIZE)).toEqual({
      x: 600 - SOL_PILL_CURSOR_OFFSET,
      y: 300 + SOL_PILL_CURSOR_OFFSET,
      ...SIZE
    })
  })

  it('flips above the cursor when there is no room below', () => {
    const r = placePill({ x: 600, y: 1000 }, WA, SIZE)
    expect(r.y).toBe(1000 - SOL_PILL_CURSOR_OFFSET - SIZE.height)
  })

  it('is clamped inside the work area at the right edge and on an offset display', () => {
    expect(placePill({ x: 1910, y: 300 }, WA, SIZE).x).toBe(1920 - SOL_PILL_WIDTH)
    const wb = { x: 1920, y: 25, width: 1440, height: 860 }
    const r = placePill({ x: 1925, y: 30 }, wb, SIZE)
    expect(r.x).toBe(1920)
    expect(r.y).toBe(30 + SOL_PILL_CURSOR_OFFSET)
  })
})

describe('growPill', () => {
  const anchor = { x: 600, y: 300 }
  const home = placePill(anchor, WA, SIZE)
  const bottom = home.y + home.height

  it('keeps the bottom edge fixed as it grows upward', () => {
    const r = growPill(anchor, home, 110, WA)
    expect(r.y + r.height).toBe(bottom)
    expect(r.height).toBe(110)
    expect(r.x).toBe(home.x)
  })

  it('shifts right of the anchor once it would cover it, and back when it shrinks', () => {
    const tall = growPill(anchor, home, 400, WA)
    expect(tall.x).toBe(anchor.x + SOL_PILL_CURSOR_OFFSET)
    expect(tall.y + tall.height).toBe(bottom)
    expect(growPill(anchor, home, 96, WA).x).toBe(home.x)
  })

  it('shifts left instead when the right has no room, and stays put when neither does', () => {
    const rightAnchor = { x: 1500, y: 300 }
    const rightHome = placePill(rightAnchor, WA, SIZE)
    expect(growPill(rightAnchor, rightHome, 400, WA).x).toBe(
      1500 - SOL_PILL_CURSOR_OFFSET - SOL_PILL_WIDTH
    )
    const narrow = { x: 0, y: 0, width: 700, height: 1040 }
    const midHome = placePill({ x: 350, y: 300 }, narrow, SIZE)
    expect(growPill({ x: 350, y: 300 }, midHome, 400, narrow).x).toBe(midHome.x)
  })

  it('clamps the height to the bounds and never rises past the work-area top', () => {
    expect(growPill(anchor, home, 10, WA).height).toBe(SOL_PILL_MIN_HEIGHT)
    const low = { x: 600, y: 900 }
    expect(growPill(low, placePill(low, WA, SIZE), 5000, WA).height).toBe(SOL_PILL_MAX_HEIGHT)
    const r = growPill(anchor, home, 600, WA)
    expect(r.y).toBe(0)
    expect(r.height).toBe(bottom)
  })

  it('treats a non-finite height as the minimum', () => {
    expect(growPill(anchor, home, Number.NaN, WA).height).toBe(SOL_PILL_MIN_HEIGHT)
  })
})
