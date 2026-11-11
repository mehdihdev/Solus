// SOLUSDEV-324: the summon picture (docs/wireflows/sol-window.md §D — "SOL can
// take a picture of your screen when you summon it … uses it for that one
// question, and then discards it"). refresh() runs at summon, before the pill
// is shown; take() hands the picture to exactly one turn; the pill hiding,
// sign-out and the setting going off clear() it. In memory only — never
// written to disk or logged (sol-window.md §6 "ephemeral by construction").
import { SUMMON_CAPTURE_WAIT_MS } from '../sol-window/solWindow.constants'
import type { ActiveWindowInfo } from './activeWindow'
import type { ScreenCapture } from './screenCapture'

/** A capture that lands later than this after its summon is dropped: the pill
 *  may already be on screen in it, and the question it was for may be gone. */
export const SUMMON_SHOT_MAX_LATENCY_MS = SUMMON_CAPTURE_WAIT_MS + 100

/** What the pill receives over sol:take-screen. */
export interface SolScreenPayload {
  /** The whole display, JPEG. */
  jpegBase64: string
  width: number
  height: number
  source: ActiveWindowInfo | null
  capturedAt: number
}

export interface SummonShotDeps {
  capture: Pick<ScreenCapture, 'captureScreen'>
  cursor(): { x: number; y: number }
  now?(): number
}

export interface SummonShot {
  /** Drop the old picture and take a new one of the display nearest `near`
   *  (else the cursor). The capture itself gates the setting. */
  refresh(near?: { x: number; y: number }): Promise<void>
  /** The picture, once; null when none. A capture still in flight never lands after. */
  take(): SolScreenPayload | null
  /** Forget it (and any capture still in flight). */
  clear(): void
}

export function createSummonShot(deps: SummonShotDeps): SummonShot {
  const now = deps.now ?? Date.now
  let shot: SolScreenPayload | null = null
  // Only the newest refresh may land; take() and clear() bump it too.
  let generation = 0
  const forget = (): void => {
    generation += 1
    shot = null
  }
  return {
    async refresh(near) {
      forget()
      const mine = generation
      const startedAt = now()
      const result = await deps.capture.captureScreen(near ?? deps.cursor()).catch(() => null)
      if (mine !== generation || result === null || 'reason' in result) return
      const landedAt = now()
      if (landedAt - startedAt > SUMMON_SHOT_MAX_LATENCY_MS) return
      shot = {
        jpegBase64: result.jpeg.toString('base64'),
        width: result.width,
        height: result.height,
        source: result.window,
        capturedAt: landedAt
      }
    },
    take() {
      const taken = shot
      forget()
      return taken
    },
    clear: forget
  }
}
