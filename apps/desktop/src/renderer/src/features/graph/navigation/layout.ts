import type { Entity } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'

export const CARD_WIDTH = 300
export const CARD_HEIGHT = 184
export const STEP_X = CARD_WIDTH + 72
export const STEP_Y = CARD_HEIGHT + 64
export const ORIGIN: Point = { x: 0, y: 0 }

const COLUMNS: readonly number[] = [0, 1, -1]
const BOUND = 100_000
/** Breathing room around the outermost cards; also where a level's containment stem starts. */
export const PAD = 80

/** Rows of three under the anchor — centre, right, left — then the next row down (design
 *  template: tidy rows, not organic packing). A cell past the coordinate boundary mirrors to
 *  the other side so a dragged-to-the-edge parent still gets children. */
function* cells(anchor: Point): Generator<Point> {
  for (let row = 0; ; row++) {
    const down = anchor.y + row * STEP_Y
    const y = Math.abs(down) <= BOUND ? down : anchor.y - row * STEP_Y
    for (const column of COLUMNS) {
      const right = anchor.x + column * STEP_X
      yield { x: Math.abs(right) <= BOUND ? right : anchor.x - column * STEP_X, y }
    }
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
 *  avoid them and fill rows below `anchor` — the parent's point, or the origin at the root. */
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
      if (!valid(point)) continue
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
  const xs = values.length ? values.map((point) => point.x) : [anchor.x]
  const ys = values.length ? values.map((point) => point.y) : [anchor.y]
  // Frame the cards themselves (design template: rows start at the top, no empty half above
  // the parent's point); an empty level frames the anchor.
  const left = Math.min(...xs) - CARD_WIDTH / 2 - PAD
  const top = Math.min(...ys) - CARD_HEIGHT / 2 - PAD
  return {
    left,
    top,
    width: Math.max(...xs) + CARD_WIDTH / 2 + PAD - left,
    height: Math.max(...ys) + CARD_HEIGHT / 2 + PAD - top
  }
}
