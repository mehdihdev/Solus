// SOLUSDEV-252 S3: pure geometry for the Ctrl-hold / circle-mode gesture
// (docs/architecture/sol-window.md §4). Path in, analysis + accept rule out.
export interface Point {
  x: number
  y: number
}

/** DIP screen coordinates. */
export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

export const GESTURE_MIN_TRAVEL_PX = 200
export const GESTURE_MIN_BBOX_PX = 40
export const GESTURE_MIN_SWEEP_DEG = 300
export const GESTURE_CLOSE_RATIO = 0.25
export const REGION_MARGIN = 0.12

export interface CircleAnalysis {
  travelPx: number
  bbox: Rect
  centroid: Point
  /** Accumulated absolute angular sweep around the bbox centroid, in degrees. */
  sweepDeg: number
  /** How closed the loop is: distance(end, loop start) / diag(bbox), where the
   *  loop starts at the point in the first third of the path nearest the end —
   *  so an approach segment (the hand moving to the thing before circling it)
   *  is excluded from the loop, its bbox and its sweep. Infinity for a
   *  degenerate bbox. */
  closeRatio: number
}

const EMPTY: CircleAnalysis = {
  travelPx: 0,
  bbox: { x: 0, y: 0, width: 0, height: 0 },
  centroid: { x: 0, y: 0 },
  sweepDeg: 0,
  closeRatio: Infinity
}

/** Signed angle change in (-π, π]. */
const wrap = (d: number): number => Math.atan2(Math.sin(d), Math.cos(d))

/** The loop is the path from the head point nearest the end (approach dropped). */
function loopOf(path: Point[]): Point[] {
  const last = path[path.length - 1]
  const headLen = Math.max(1, Math.ceil(path.length / 3))
  let k = 0
  let best = Infinity
  for (let i = 0; i < headLen; i++) {
    const d = Math.hypot(last.x - path[i].x, last.y - path[i].y)
    if (d < best) {
      best = d
      k = i
    }
  }
  return path.slice(k)
}

export function analyse(raw: Point[]): CircleAnalysis {
  if (raw.length === 0) return EMPTY
  const path = loopOf(raw)
  const first = path[0]
  const last = path[path.length - 1]
  if (!first || !last) return EMPTY
  const xs = path.map((p) => p.x)
  const ys = path.map((p) => p.y)
  const bbox = {
    x: Math.min(...xs),
    y: Math.min(...ys),
    width: Math.max(...xs) - Math.min(...xs),
    height: Math.max(...ys) - Math.min(...ys)
  }
  const centroid = { x: bbox.x + bbox.width / 2, y: bbox.y + bbox.height / 2 }
  const angle = (p: Point): number => Math.atan2(p.y - centroid.y, p.x - centroid.x)
  let travelPx = 0
  let sweep = 0
  for (let i = 1; i < path.length; i++) {
    travelPx += Math.hypot(path[i].x - path[i - 1].x, path[i].y - path[i - 1].y)
    sweep += wrap(angle(path[i]) - angle(path[i - 1]))
  }
  const diag = Math.hypot(bbox.width, bbox.height)
  const gap = Math.hypot(last.x - first.x, last.y - first.y)
  const closeRatio = diag === 0 ? Infinity : gap / diag
  return { travelPx, bbox, centroid, sweepDeg: Math.abs(sweep) * (180 / Math.PI), closeRatio }
}

export function isCircle(a: CircleAnalysis): boolean {
  return (
    a.travelPx >= GESTURE_MIN_TRAVEL_PX &&
    a.bbox.width >= GESTURE_MIN_BBOX_PX &&
    a.bbox.height >= GESTURE_MIN_BBOX_PX &&
    a.sweepDeg >= GESTURE_MIN_SWEEP_DEG &&
    a.closeRatio <= GESTURE_CLOSE_RATIO
  )
}

/** bbox + 12 % margin per side, clamped to the display, integer DIPs. */
export function regionFor(a: CircleAnalysis, display: { bounds: Rect }): Rect {
  const { bbox } = a
  const b = display.bounds
  const x0 = Math.max(b.x, Math.round(bbox.x - bbox.width * REGION_MARGIN))
  const y0 = Math.max(b.y, Math.round(bbox.y - bbox.height * REGION_MARGIN))
  const x1 = Math.min(b.x + b.width, Math.round(bbox.x + bbox.width * (1 + REGION_MARGIN)))
  const y1 = Math.min(b.y + b.height, Math.round(bbox.y + bbox.height * (1 + REGION_MARGIN)))
  return { x: x0, y: y0, width: Math.max(0, x1 - x0), height: Math.max(0, y1 - y0) }
}
