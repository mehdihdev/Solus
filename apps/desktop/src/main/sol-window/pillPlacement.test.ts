// SOLUSDEV-319: the pill's live placement — summon at the cursor, grow from the
// summon home, and adopt a user drag as the new home (bottom edge fixed, no
// shift-aside, still clamped to the work area).
import { describe, it, expect } from 'vitest'
import { createPillPlacement } from './pillPlacement'
import { growPill, placePill, SOL_PILL_INITIAL_HEIGHT, SOL_PILL_WIDTH } from './pillGeometry'

const WA = { x: 0, y: 0, width: 1920, height: 1040 }
const WB = { x: 1920, y: 0, width: 1440, height: 800 }
const screen = {
  getDisplayNearestPoint: (p: { x: number; y: number }) => ({ workArea: p.x >= 1920 ? WB : WA })
}
const pill = { width: SOL_PILL_WIDTH, height: SOL_PILL_INITIAL_HEIGHT }

describe('createPillPlacement', () => {
  it('grows nothing before the first summon', () => {
    expect(createPillPlacement(screen).grow(300)).toBeNull()
  })

  it('summons at the cursor and grows from that home with the shift-aside rule', () => {
    const p = createPillPlacement(screen)
    const near = { x: 600, y: 300 }
    const home = placePill(near, WA, pill)
    expect(p.summon(near, true)).toEqual(home)
    expect(p.grow(400)).toEqual(growPill(near, home, 400, WA))
  })

  it('ignores its own setBounds echoed back as a move', () => {
    const p = createPillPlacement(screen)
    const near = { x: 600, y: 300 }
    p.summon(near, true)
    const grown = p.grow(400)
    if (grown === null) throw new Error('expected bounds')
    p.moved(grown)
    expect(p.grow(400)).toEqual(grown)
  })

  it('a drag becomes the new home: growth keeps the dragged bottom edge and x', () => {
    const p = createPillPlacement(screen)
    p.summon({ x: 600, y: 300 }, true)
    p.grow(200)
    const dragged = { x: 900, y: 500, width: SOL_PILL_WIDTH, height: 200 }
    p.moved(dragged)
    const r = p.grow(400)
    expect(r).toEqual({ x: 900, y: 300, width: SOL_PILL_WIDTH, height: 400 })
    expect(p.grow(150)).toEqual({ x: 900, y: 550, width: SOL_PILL_WIDTH, height: 150 })
  })

  it('a grow during a drag (before the moved event) keeps the window where the user has it', () => {
    const p = createPillPlacement(screen)
    p.summon({ x: 600, y: 300 }, true)
    const dragging = { x: 1000, y: 500, width: SOL_PILL_WIDTH, height: SOL_PILL_INITIAL_HEIGHT }
    const grown = p.grow(400, dragging)
    if (grown === null) throw new Error('expected bounds')
    expect(grown.x).toBe(1000)
    expect(grown.y + grown.height).toBe(dragging.y + dragging.height)
  })

  it('moved answers whether it was a drag: its own setBounds is not', () => {
    const p = createPillPlacement(screen)
    const home = p.summon({ x: 600, y: 300 }, true)
    expect(p.moved({ ...home, y: home.y + 1 })).toBe(false)
    expect(p.moved({ ...home, x: home.x + 300 })).toBe(true)
  })

  it('treats a rect within a couple of pixels of its own setBounds as its own', () => {
    const p = createPillPlacement(screen)
    const near = { x: 600, y: 300 }
    const home = p.summon(near, true)
    p.moved({ ...home, x: home.x + 1 })
    expect(p.grow(400)).toEqual(growPill(near, placePill(near, WA, pill), 400, WA))
  })

  it('a drag onto another display clamps to that work area and its height cap', () => {
    const p = createPillPlacement(screen)
    p.summon({ x: 600, y: 300 }, true)
    p.moved({ x: 3300, y: 700, width: SOL_PILL_WIDTH, height: 200 })
    const r = p.grow(5000)
    expect(r?.x).toBe(1920 + 1440 - SOL_PILL_WIDTH)
    expect(r?.height).toBe(480) // 60 % of 800
    expect((r?.y ?? 0) + (r?.height ?? 0)).toBe(800)
  })

  it('a fresh summon after a drag places the pill at the cursor again', () => {
    const p = createPillPlacement(screen)
    p.summon({ x: 600, y: 300 }, true)
    p.moved({ x: 900, y: 500, width: SOL_PILL_WIDTH, height: 200 })
    expect(p.summon({ x: 100, y: 100 }, true)).toEqual(placePill({ x: 100, y: 100 }, WA, pill))
  })
})
