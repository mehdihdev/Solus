// SOLUSDEV-252 S3: polls the cursor at ~60 Hz ONLY while armed
// (docs/architecture/sol-window.md §2). The scheduler is injected so tests
// drive time; the wiring passes Node's setInterval/clearInterval.
import type { Point } from './circleDetector'

// ponytail: fixed 60 Hz; go adaptive (slow down when the cursor rests) only if CPU shows.
export const SAMPLE_INTERVAL_MS = 16

export interface Scheduler {
  setInterval(cb: () => void, ms: number): unknown
  clearInterval(handle: unknown): void
}

export interface CursorSamplerDeps {
  getCursor(): Point
  now(): number
  scheduler: Scheduler
  onSample(t: number, at: Point): void
}

export interface CursorSampler {
  arm(): void
  disarm(): void
  isArmed(): boolean
}

export function createCursorSampler(deps: CursorSamplerDeps): CursorSampler {
  let handle: unknown = null
  return {
    arm() {
      if (handle !== null) return
      handle = deps.scheduler.setInterval(
        () => deps.onSample(deps.now(), deps.getCursor()),
        SAMPLE_INTERVAL_MS
      )
    },
    disarm() {
      if (handle === null) return
      deps.scheduler.clearInterval(handle)
      handle = null
    },
    isArmed: () => handle !== null
  }
}
