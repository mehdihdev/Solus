// SOLUSDEV-319: the Ember Pill's live placement (docs/architecture/sol-window.md
// "SOLUSDEV-319 Ember Pill"). Where the pointer was at summon, the collapsed
// "home" rect there, the last height the renderer asked for — and, once the
// user drags the pill, the dragged rect becomes home (no shift-aside anchor)
// so later growth keeps their position with the bottom edge fixed.
import {
  dragHome,
  growPill,
  placePill,
  SOL_PILL_INITIAL_HEIGHT,
  SOL_PILL_WIDTH,
  type Point,
  type Rect
} from './pillGeometry'

export interface PillScreen {
  getDisplayNearestPoint(point: Point): { workArea: Rect }
}

export interface PillPlacement {
  /** Re-anchor at `near`: the collapsed placement, grown to the current
   *  height — or collapsed, for a `fresh` summon. */
  summon(near: Point, fresh?: boolean): Rect
  /** The renderer's height; null before the first summon. `current` is the
   *  window's live bounds: a drag still in progress (macOS sends 'moved' only
   *  when it ends) is adopted first, so growth never snaps the pill back. */
  grow(height: number, current?: Rect): Rect | null
  /** The window moved. Our own setBounds is ignored; anything else is a drag. */
  moved(bounds: Rect): void
}

/** The OS may nudge a programmatic setBounds by a pixel or two; that is not a drag. */
const SAME_RECT_TOLERANCE = 2
const near = (a: number, b: number): boolean => Math.abs(a - b) <= SAME_RECT_TOLERANCE
const sameRect = (a: Rect | null, b: Rect): boolean =>
  a !== null &&
  near(a.x, b.x) &&
  near(a.y, b.y) &&
  near(a.width, b.width) &&
  near(a.height, b.height)

const bottomCentre = (r: Rect): Point => ({ x: r.x + r.width / 2, y: r.y + r.height })

export function createPillPlacement(screen: PillScreen): PillPlacement {
  let anchor: Point | null = null
  let home: Rect | null = null
  let height: number = SOL_PILL_INITIAL_HEIGHT
  let lastSet: Rect | null = null
  const workAreaAt = (p: Point): Rect => screen.getDisplayNearestPoint(p).workArea
  const remember = (r: Rect): Rect => (lastSet = r)
  const moved = (bounds: Rect): void => {
    if (home === null || sameRect(lastSet, bounds)) return
    home = dragHome(bounds, workAreaAt(bottomCentre(bounds)))
    anchor = null
    lastSet = bounds
  }
  return {
    summon(near, fresh = false) {
      if (fresh) height = SOL_PILL_INITIAL_HEIGHT
      const wa = workAreaAt(near)
      anchor = near
      home = placePill(near, wa, { width: SOL_PILL_WIDTH, height: SOL_PILL_INITIAL_HEIGHT })
      return remember(height === SOL_PILL_INITIAL_HEIGHT ? home : growPill(near, home, height, wa))
    },
    grow(next, current) {
      if (home === null) return null
      if (current) moved(current)
      height = next
      return remember(growPill(anchor, home, next, workAreaAt(anchor ?? bottomCentre(home))))
    },
    moved
  }
}
