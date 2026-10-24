// SOLUSDEV-319: the Ember Pill's placement, pure (docs/architecture/sol-window.md
// "SOLUSDEV-319 Ember Pill"). Summoned next to the cursor; grows upward with its
// bottom edge fixed; shifts aside rather than cover the point the pointer was on.
// Geometry is recomputed per summon — nothing here is persisted.

export const SOL_PILL_WIDTH = 560
/** The collapsed pill (bar + footer + shadow room) before the renderer measures itself. */
export const SOL_PILL_INITIAL_HEIGHT = 112
export const SOL_PILL_MIN_HEIGHT = 80
export const SOL_PILL_MAX_HEIGHT = 620
export const SOL_PILL_CURSOR_OFFSET = 24

export interface Point {
  x: number
  y: number
}
export interface Size {
  width: number
  height: number
}
export interface Rect extends Point, Size {}

const clamp = (n: number, lo: number, hi: number): number => Math.min(Math.max(n, lo), hi)

/** Below-left of the cursor; above it when the bottom has no room; inside the work area. */
export function placePill(cursor: Point, workArea: Rect, size: Size): Rect {
  const right = workArea.x + workArea.width
  const bottom = workArea.y + workArea.height
  const below = cursor.y + SOL_PILL_CURSOR_OFFSET
  const y = below + size.height <= bottom ? below : cursor.y - SOL_PILL_CURSOR_OFFSET - size.height
  return {
    x: clamp(
      cursor.x - SOL_PILL_CURSOR_OFFSET,
      workArea.x,
      Math.max(workArea.x, right - size.width)
    ),
    y: clamp(y, workArea.y, Math.max(workArea.y, bottom - size.height)),
    ...size
  }
}

const covers = (r: Rect, p: Point): boolean =>
  p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height

/** `home` is the summon placement; the grown rect keeps its bottom edge. If the
 *  taller rect would cover `anchor`, it moves right of it, else left, else stays. */
export function growPill(anchor: Point, home: Rect, height: number, workArea: Rect): Rect {
  const bottom = home.y + home.height
  const wanted = Number.isFinite(height) ? height : SOL_PILL_MIN_HEIGHT
  const h = Math.min(clamp(wanted, SOL_PILL_MIN_HEIGHT, SOL_PILL_MAX_HEIGHT), bottom - workArea.y)
  const grown = { x: home.x, y: bottom - h, width: home.width, height: h }
  if (!covers(grown, anchor)) return grown
  const toRight = anchor.x + SOL_PILL_CURSOR_OFFSET
  if (toRight + home.width <= workArea.x + workArea.width) return { ...grown, x: toRight }
  const toLeft = anchor.x - SOL_PILL_CURSOR_OFFSET - home.width
  if (toLeft >= workArea.x) return { ...grown, x: toLeft }
  return grown
}
