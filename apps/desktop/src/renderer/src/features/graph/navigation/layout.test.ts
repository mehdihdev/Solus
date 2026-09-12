// SOLUSDEV-250 P5 — unsaved cells spiral around the level's anchor and the frame
// is centred on it; at the root (anchor = origin) nothing changes.
import { describe, expect, it } from 'vitest'
import type { Entity } from '../../../lib/api/resources'
import { CARD_HEIGHT, CARD_WIDTH, layoutLevel, levelBounds, ORIGIN, STEP_X, STEP_Y } from './layout'

const node = (id: string): Entity => ({
  id,
  type: 'part',
  name: id,
  domain: 'mechanical',
  source_key: id
})
const anchor = { x: 320, y: 60 }

describe('layoutLevel', () => {
  it('packs the first unsaved node on the anchor and the next ones one step out from it', () => {
    const points = layoutLevel([node('a'), node('b')], {}, anchor)
    expect(points.a).toEqual(anchor)
    expect(points.b).toEqual({ x: anchor.x - STEP_X, y: anchor.y - STEP_Y })
  })

  it('leaves a saved node where it is and packs the rest around the anchor', () => {
    const saved = { b: { x: 5, y: 5 } }
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
  it('centres the frame on the anchor with half-extents measured from it', () => {
    const bounds = levelBounds({ a: anchor, b: { x: anchor.x + 100, y: anchor.y - 40 } }, anchor)
    const halfWidth = 100 + CARD_WIDTH / 2 + 80
    const halfHeight = 40 + CARD_HEIGHT / 2 + 80
    expect(bounds).toEqual({
      left: anchor.x - halfWidth,
      top: anchor.y - halfHeight,
      width: halfWidth * 2,
      height: halfHeight * 2
    })
  })

  it('centres the origin by default', () => {
    const half = { x: 100 + CARD_WIDTH / 2 + 80, y: 40 + CARD_HEIGHT / 2 + 80 }
    expect(levelBounds({ a: { x: 100, y: -40 } })).toEqual({
      left: -half.x,
      top: -half.y,
      width: half.x * 2,
      height: half.y * 2
    })
  })
})
