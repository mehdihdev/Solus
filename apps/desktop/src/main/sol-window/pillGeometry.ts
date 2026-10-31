// SOLUSDEV-319: the Ember Pill's placement, pure (docs/architecture/sol-window.md
// "SOLUSDEV-319 Ember Pill"). Summoned next to the cursor; grows upward with its
// bottom edge fixed; shifts aside rather than cover the point the pointer was on.
// Geometry is recomputed per summon (or adopted from a drag) — nothing here is
// persisted. The height is capped at min(620, 60 % of the work area).

export const SOL_PILL_WIDTH = 560
/** The collapsed pill (bar + footer + shadow room) before the renderer measures itself. */
export const SOL_PILL_INITIAL_HEIGHT = 112
export const SOL_PILL_MIN_HEIGHT = 80
export const SOL_PILL_MAX_HEIGHT = 620
/** The pill never takes more than this share of the display's work area. */
export const SOL_PILL_MAX_SCREEN_FRACTION = 0.6
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

/** The tallest the pill may be on this work area: min(620, 60 % of its height). */
export function pillMaxHeight(workArea: Rect): number {
  return Math.min(SOL_PILL_MAX_HEIGHT, Math.floor(workArea.height * SOL_PILL_MAX_SCREEN_FRACTION))
}

/** `home` is the summon (or dragged) placement; the grown rect keeps its bottom
 *  edge, sliding down only when the top would leave the work area. If the
 *  taller rect would cover `anchor`, it moves right of it, else left, else
 *  stays. A null anchor (the user dragged the pill) never shifts aside. */
export function growPill(anchor: Point | null, home: Rect, height: number, workArea: Rect): Rect {
  const bottom = home.y + home.height
  const wanted = Number.isFinite(height) ? height : SOL_PILL_MIN_HEIGHT
  const h = clamp(
    wanted,
    SOL_PILL_MIN_HEIGHT,
    Math.max(SOL_PILL_MIN_HEIGHT, pillMaxHeight(workArea))
  )
  const grown = { x: home.x, y: Math.max(workArea.y, bottom - h), width: home.width, height: h }
  if (anchor === null || !covers(grown, anchor)) return grown
  const toRight = anchor.x + SOL_PILL_CURSOR_OFFSET
  if (toRight + home.width <= workArea.x + workArea.width) return { ...grown, x: toRight }
  const toLeft = anchor.x - SOL_PILL_CURSOR_OFFSET - home.width
  if (toLeft >= workArea.x) return { ...grown, x: toLeft }
  return grown
}

/** Where the user dragged the pill becomes its new home, pulled back inside
 *  the work area (its bottom edge at least the minimum height below the top). */
export function dragHome(bounds: Rect, workArea: Rect): Rect {
  const right = workArea.x + workArea.width
  const bottom = clamp(
    bounds.y + bounds.height,
    workArea.y + SOL_PILL_MIN_HEIGHT,
    workArea.y + workArea.height
  )
  return {
    ...bounds,
    x: clamp(bounds.x, workArea.x, Math.max(workArea.x, right - bounds.width)),
    y: bottom - bounds.height
  }
}
