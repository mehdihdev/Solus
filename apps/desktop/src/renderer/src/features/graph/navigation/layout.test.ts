// Unsaved cells fill rows of three below the level's anchor (design template) and the
// frame hugs the cards, so a level never opens on an empty half above its parent's point.
import { describe, expect, it } from 'vitest'
import type { Entity } from '../../../lib/api/resources'
import {
  CARD_HEIGHT,
  CARD_WIDTH,
  layoutLevel,
  levelBounds,
  ORIGIN,
  PAD,
  STEP_X,
  STEP_Y
} from './layout'

const node = (id: string): Entity => ({
  id,
  type: 'part',
  name: id,
  domain: 'mechanical',
  source_key: id
})
const anchor = { x: 320, y: 60 }

describe('layoutLevel', () => {
  it('fills tidy rows of three below the parent — centre, right, left — deterministically', () => {
    const points = layoutLevel([node('a'), node('b'), node('c'), node('d')], {}, anchor)
    expect(points.a).toEqual(anchor)
    expect(points.b).toEqual({ x: anchor.x + STEP_X, y: anchor.y })
    expect(points.c).toEqual({ x: anchor.x - STEP_X, y: anchor.y })
    expect(points.d).toEqual({ x: anchor.x, y: anchor.y + STEP_Y })
    const nodes = Array.from({ length: 24 }, (_, i) => node(String(i)))
    const packed = layoutLevel(nodes, {}, anchor)
    expect(layoutLevel(nodes, {}, anchor)).toEqual(packed)
    expect(new Set(Object.values(packed).map((p) => p.x)).size).toBe(3)
    expect(new Set(Object.values(packed).map((p) => p.y)).size).toBe(8)
    for (const [id, point] of Object.entries(packed)) {
      for (const [otherId, other] of Object.entries(packed)) {
        if (id !== otherId)
          expect(
            Math.abs(point.x - other.x) >= CARD_WIDTH + 24 ||
              Math.abs(point.y - other.y) >= CARD_HEIGHT + 24
          ).toBe(true)
      }
    }
    expect(layoutLevel([...nodes, node('new')], packed, anchor)).toMatchObject(packed)
  })

  it('leaves a saved node where it is and packs the rest around the anchor', () => {
    const saved = { b: { x: -20, y: 5 } }
    const points = layoutLevel([node('a'), node('b')], saved, anchor)
    expect(points.b).toEqual(saved.b)
    expect(points.a).toEqual(anchor)
  })

  it('is unchanged at the root: the default anchor is the origin', () => {
    expect(ORIGIN).toEqual({ x: 0, y: 0 })
    expect(layoutLevel([node('a'), node('b')], {})).toEqual(
      layoutLevel([node('a'), node('b')], {}, ORIGIN)
    )
    expect(layoutLevel([node('a')], {}).a).toEqual(ORIGIN)
  })
})

describe('levelBounds', () => {
  it('frames the cards themselves with padding, not the anchor', () => {
    const bounds = levelBounds({ a: anchor, b: { x: anchor.x + 100, y: anchor.y - 40 } }, anchor)
    expect(bounds).toEqual({
      left: anchor.x - CARD_WIDTH / 2 - PAD,
      top: anchor.y - 40 - CARD_HEIGHT / 2 - PAD,
      width: 100 + CARD_WIDTH + PAD * 2,
      height: 40 + CARD_HEIGHT + PAD * 2
    })
  })

  it('opens on the first row: rows below the anchor leave no empty space above it', () => {
    const points = layoutLevel([node('a'), node('b'), node('c'), node('d')], {}, anchor)
    const bounds = levelBounds(points, anchor)
    expect(bounds.top).toBe(anchor.y - CARD_HEIGHT / 2 - PAD)
    expect(bounds.height).toBe(STEP_Y + CARD_HEIGHT + PAD * 2)
  })

  it('frames the anchor when the level is empty', () => {
    expect(levelBounds({}, anchor)).toEqual({
      left: anchor.x - CARD_WIDTH / 2 - PAD,
      top: anchor.y - CARD_HEIGHT / 2 - PAD,
      width: CARD_WIDTH + PAD * 2,
      height: CARD_HEIGHT + PAD * 2
    })
  })
})

it('packs new children inside the API coordinate boundary even at a dragged corner', () => {
  const result = layoutLevel(
    Array.from({ length: 24 }, (_, i) => node(String(i))),
    {},
    { x: 100000, y: 100000 }
  )
  expect(
    Object.values(result).every(
      (point) => Math.abs(point.x) <= 100000 && Math.abs(point.y) <= 100000
    )
  ).toBe(true)
})
