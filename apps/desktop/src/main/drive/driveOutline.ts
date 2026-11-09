// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5 "While a step
// runs"): while the renderer says a drive.step runs, main draws an amber
// outline as four click-through strips just OUTSIDE the latest drive_window
// bounds — never over the window, which the helper's hit-test (§2 check 5)
// would refuse as `occluded` — and quiets the double-tap-Ctrl and circle
// detectors, plus a short tail. Geometry is pure; windows enter through
// `createStrip`, so nothing here touches Electron.
import type { Rect } from '../capture/screenCapture'

export const OUTLINE_THICKNESS_PX = 3
/** The detectors stay quiet this long after a step ends. */
export const DRIVE_QUIET_TAIL_MS = 300
/** The step's 120 s budget plus margin: main ends a session the renderer never ended. */
export const DRIVE_SAFETY_TIMEOUT_MS = 150_000

/** Top, bottom, left, right — whole pixels, rounded outward so no strip ever
 *  covers a fractional edge of the window. */
export function outlineStrips(window: Rect, thickness = OUTLINE_THICKNESS_PX): Rect[] {
  const left = Math.floor(window.x)
  const top = Math.floor(window.y)
  const right = Math.ceil(window.x + window.width)
  const bottom = Math.ceil(window.y + window.height)
  const t = thickness
  return [
    { x: left - t, y: top - t, width: right - left + 2 * t, height: t },
    { x: left - t, y: bottom, width: right - left + 2 * t, height: t },
    { x: left - t, y: top, width: t, height: bottom - top },
    { x: right, y: top, width: t, height: bottom - top }
  ]
}

/** The slice of a strip window the session drives. */
export interface OutlineStrip {
  setBounds(bounds: Rect): void
  showInactive(): void
  hide(): void
  destroy(): void
  isDestroyed(): boolean
}

export interface DriveSessionDeps {
  createStrip(): OutlineStrip
  now(): number
  setTimeout(cb: () => void, ms: number): unknown
  clearTimeout(handle: unknown): void
}

export interface DriveSession {
  /** A renderer's sol.setDriving, keyed by its webContents id: driving while
   *  ANY sender says true. */
  setDriving(senderId: number, active: boolean): void
  /** The sender's window went away — counts as its false. */
  releaseSender(senderId: number): void
  /** The latest drive_window bounds (null: unknown, e.g. the companion restarted). */
  setBounds(bounds: Rect | null): void
  /** The hotkey detectors ignore input while this is true. */
  isQuiet(): boolean
  dispose(): void
}

/** Run a strip call; a strip that failed is dropped and rebuilt next draw. */
function attempt(fn: () => void): boolean {
  try {
    fn()
    return true
  } catch {
    return false
  }
}

export function createDriveSession(deps: DriveSessionDeps): DriveSession {
  const senders = new Set<number>()
  let driving = false
  let endedAt = Number.NEGATIVE_INFINITY
  let bounds: Rect | null = null
  let safety: unknown = null
  let strips: OutlineStrip[] = []

  const hideAll = (): void => {
    for (const s of strips) if (!s.isDestroyed()) attempt(() => s.hide())
  }

  const draw = (): void => {
    if (!driving || bounds === null) return hideAll()
    const rects = outlineStrips(bounds)
    strips = rects.map((rect, i) => {
      const existing = strips[i]
      const strip = existing && !existing.isDestroyed() ? existing : deps.createStrip()
      attempt(() => {
        strip.setBounds(rect)
        strip.showInactive()
      })
      return strip
    })
  }

  /** Every sender's session ends; the bounds go too, so the next step never
   *  flashes the previous step's outline before its first drive_window. */
  const end = (): void => {
    if (safety !== null) deps.clearTimeout(safety)
    safety = null
    senders.clear()
    if (driving) endedAt = deps.now()
    driving = false
    bounds = null
    draw()
  }

  const release = (senderId: number): void => {
    if (!senders.delete(senderId)) return
    if (senders.size === 0) end()
  }

  return {
    setDriving(senderId, active) {
      if (!active) return release(senderId)
      senders.add(senderId)
      if (safety !== null) deps.clearTimeout(safety)
      safety = deps.setTimeout(end, DRIVE_SAFETY_TIMEOUT_MS)
      driving = true
      draw()
    },
    releaseSender: release,
    setBounds(next) {
      bounds = next
      draw()
    },
    isQuiet: () => driving || deps.now() - endedAt < DRIVE_QUIET_TAIL_MS,
    dispose() {
      end()
      for (const s of strips) if (!s.isDestroyed()) attempt(() => s.destroy())
      strips = []
    }
  }
}
