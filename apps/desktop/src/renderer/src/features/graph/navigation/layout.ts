import type { Entity } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'

export const CARD_WIDTH = 224
export const CARD_HEIGHT = 164
export const STEP_X = CARD_WIDTH + 72
export const STEP_Y = CARD_HEIGHT + 64
export const ORIGIN: Point = { x: 0, y: 0 }

function* cells(anchor: Point): Generator<Point> {
  const at = (x: number, y: number): Point => ({
    x: anchor.x + x * STEP_X,
    y: anchor.y + y * STEP_Y
  })
  yield at(0, 0)
  for (let ring = 1; ; ring++) {
    for (let x = -ring; x <= ring; x++) yield at(x, -ring)
    for (let y = -ring + 1; y <= ring; y++) yield at(ring, y)
    for (let x = ring - 1; x >= -ring; x--) yield at(x, ring)
    for (let y = ring - 1; y > -ring; y--) yield at(-ring, y)
  }
}

function valid(point: Point | undefined): point is Point {
  return (
    point !== undefined &&
    Number.isFinite(point.x) &&
    Number.isFinite(point.y) &&
    Math.abs(point.x) <= 100_000 &&
    Math.abs(point.y) <= 100_000
  )
}

export function boundedPoint(point: Point): Point {
  return {
    x: Math.max(-100_000, Math.min(100_000, point.x)),
    y: Math.max(-100_000, Math.min(100_000, point.y))
  }
}

/** Lay out only this page. Saved coordinates are authoritative; new defaults
 *  avoid them and spiral out from `anchor` — the parent's point, or the origin at the root. */
export function layoutLevel(
  entities: readonly Entity[],
  saved: Readonly<Record<string, Point>>,
  anchor: Point = ORIGIN
): Record<string, Point> {
  const points: Record<string, Point> = {}
  for (const entity of entities) if (valid(saved[entity.id])) points[entity.id] = saved[entity.id]
  const available = cells(anchor)
  for (const entity of entities) {
    if (points[entity.id]) continue
    for (;;) {
      const next = available.next()
      if (next.done) break
      const point = next.value
      if (
        Object.values(points).some(
          (other) =>
            Math.abs(point.x - other.x) < CARD_WIDTH + 24 &&
            Math.abs(point.y - other.y) < CARD_HEIGHT + 24
        )
      )
        continue
      points[entity.id] = point
      break
    }
  }
  return points
}

/** Fixed card sizes keep dense levels readable; overflow is scrollable, never tiny text. */
export interface LevelBounds {
  left: number
  top: number
  width: number
  height: number
}

export function levelBounds(
  points: Readonly<Record<string, Point>>,
  anchor: Point = ORIGIN
): LevelBounds {
  const values = Object.values(points)
  const halfWidth =
    Math.max(0, ...values.map((point) => Math.abs(point.x - anchor.x))) + CARD_WIDTH / 2 + 80
  const halfHeight =
    Math.max(0, ...values.map((point) => Math.abs(point.y - anchor.y))) + CARD_HEIGHT / 2 + 80
  // Center the anchor, never the current cluster's uneven bounding box.
  return {
    left: anchor.x - halfWidth,
    top: anchor.y - halfHeight,
    width: halfWidth * 2,
    height: halfHeight * 2
  }
}
